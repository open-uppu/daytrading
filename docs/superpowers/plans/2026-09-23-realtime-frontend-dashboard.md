# Real-time Web Frontend Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-dependency, real-time web frontend dashboard in an isolated `frontend/` directory that serves as an in-browser replacement for MetaTrader 5 (MT5), showing live candlestick charts, account KPIs, daily target progress, open positions, closed trade history, and specialist AI squad statuses.

**Architecture:** A FastAPI APIRouter and WebSocket Hub (`/ws/live`) embedded in `frontend/` mounted onto the existing bridge server, serving static assets (HTML5, Tailwind CDN, TradingView Lightweight Charts v4, custom vanilla JS/CSS). A dual-mode `feed_provider` supplies live telemetry from MT5 with automatic fallback to `PaperTradingBroker`.

**Tech Stack:** Python 3.11+, FastAPI, WebSockets, TradingView Lightweight Charts v4 (CDN), Tailwind CSS (CDN), HTML5/ES6 JavaScript.

## Global Constraints

- All frontend files must strictly reside in the isolated `frontend/` directory (`frontend/static/`, `frontend/router.py`, `frontend/feed_provider.py`).
- Read-Only / Monitoring Only: Zero trade execution buttons or dangerous endpoints on the frontend.
- Zero npm/node build dependencies: All UI libraries must be CDN-based.
- Dual-mode support: Seamlessly works with both MT5 Live Bridge and offline PaperTrading simulation.
- TDD: Every Python component must have automated tests using `pytest`.

---

### Task 1: Dual-Mode Feed Provider (`frontend/feed_provider.py`)

**Files:**
- Create: `frontend/__init__.py`
- Create: `frontend/feed_provider.py`
- Test: `tests/test_frontend_feed.py`

**Interfaces:**
- Produces: `DashboardFeedProvider.get_snapshot(symbol: str, timeframe: str) -> Dict[str, Any]`
- Produces: `DashboardFeedProvider.get_bars_payload(symbol: str, timeframe: str) -> Dict[str, Any]`

- [ ] **Step 1: Write the failing test for `DashboardFeedProvider`**

```python
# tests/test_frontend_feed.py
import pytest
from frontend.feed_provider import DashboardFeedProvider

def test_feed_provider_fallback_paper_snapshot():
    provider = DashboardFeedProvider()
    snapshot = provider.get_snapshot(symbol="XAUUSD", timeframe="M5")
    
    assert "account" in snapshot
    assert "portfolio" in snapshot
    assert "bars" in snapshot
    assert "open_positions" in snapshot
    assert "closed_orders" in snapshot
    assert "specialists" in snapshot
    assert snapshot["symbol"] == "XAUUSD"
    assert snapshot["timeframe"] == "M5"
    assert isinstance(snapshot["bars"], list)
    assert len(snapshot["bars"]) > 0
    assert "close" in snapshot["bars"][-1]

def test_feed_provider_get_bars():
    provider = DashboardFeedProvider()
    payload = provider.get_bars_payload(symbol="BTCUSD", timeframe="M15")
    assert payload["symbol"] == "BTCUSD"
    assert payload["timeframe"] == "M15"
    assert len(payload["bars"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_frontend_feed.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'frontend'`

- [ ] **Step 3: Implement `frontend/__init__.py` and `frontend/feed_provider.py`**

```python
# frontend/__init__.py
"""Frontend package for Pilotfish Real-time Web Dashboard."""
```

```python
# frontend/feed_provider.py
"""Dual-mode data provider for the Pilotfish Real-time Web Dashboard."""
from typing import Dict, Any, List, Optional
import time
from datetime import datetime, timezone
import pandas as pd
from config import config
from mt4.paper_broker import PaperTradingBroker

class DashboardFeedProvider:
    """Provides snapshot and live candle/account data from MT5 state or PaperTrading fallback."""

    def __init__(self, mt5_state_ref: Optional[Dict[str, Any]] = None, cached_bars_ref: Optional[Dict[str, Any]] = None):
        self._mt5_state = mt5_state_ref
        self._cached_bars = cached_bars_ref
        self._paper_broker = PaperTradingBroker(initial_balance=config.initial_balance)

    def get_account_data(self) -> Dict[str, Any]:
        """Returns account balance, equity, and connectivity status."""
        if self._mt5_state and self._mt5_state.get("connected"):
            balance = float(self._mt5_state.get("balance", config.initial_balance))
            equity = float(self._mt5_state.get("equity", balance))
            floating = equity - balance
            return {
                "account_number": self._mt5_state.get("account_number", config.mt5_login),
                "server": self._mt5_state.get("server", config.mt5_server),
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "floating_pnl": round(floating, 2),
                "connected": True,
                "last_sync": self._mt5_state.get("last_sync", datetime.now(timezone.utc).isoformat()),
                "mode": "MT5 LIVE"
            }
        
        # Paper fallback
        acc = self._paper_broker.get_account_info()
        balance = float(acc["balance"])
        equity = float(acc["equity"])
        floating = equity - balance
        return {
            "account_number": 99999999,
            "server": "PaperTrading-Simulation",
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "floating_pnl": round(floating, 2),
            "connected": True,
            "last_sync": datetime.now(timezone.utc).isoformat(),
            "mode": "PAPER SIMULATION"
        }

    def get_portfolio_metrics(self) -> Dict[str, Any]:
        """Calculates daily target progress metrics."""
        account = self.get_account_data()
        start_bal = config.initial_balance
        realized = account["balance"] - start_bal
        daily_pct = round((realized / start_bal) * 100.0, 2) if start_bal > 0 else 0.0
        equity_pnl = account["equity"] - start_bal
        equity_pct = round((equity_pnl / start_bal) * 100.0, 2) if start_bal > 0 else 0.0

        return {
            "starting_balance": start_bal,
            "realized_pnl_usd": round(realized, 2),
            "equity_pnl_usd": round(equity_pnl, 2),
            "daily_return_pct": daily_pct,
            "equity_return_pct": equity_pct,
            "target_pct": config.daily_target_pct * 100.0,
            "target_profit_usd": round(start_bal * config.daily_target_pct, 2),
            "hard_target_pct": config.daily_target_hard_pct * 100.0,
            "hard_target_profit_usd": round(start_bal * config.daily_target_hard_pct, 2),
            "max_loss_pct": config.daily_max_loss_pct * 100.0,
            "max_loss_usd": round(start_bal * config.daily_max_loss_pct, 2),
            "target_reached": daily_pct >= (config.daily_target_pct * 100.0),
            "hard_target_reached": daily_pct >= (config.daily_target_hard_pct * 100.0),
            "max_loss_reached": equity_pct <= -(config.daily_max_loss_pct * 100.0)
        }

    def get_bars_list(self, symbol: str, timeframe: str = "M5") -> List[Dict[str, Any]]:
        """Returns formatted bars for TradingView Lightweight Charts (time in unix sec)."""
        key = f"{symbol.upper()}:{timeframe.upper()}"
        if self._cached_bars and key in self._cached_bars and self._cached_bars[key].get("bars"):
            raw_bars = self._cached_bars[key]["bars"]
            # Ensure time is unix timestamp integer
            formatted = []
            for b in raw_bars:
                t = b.get("time") or b.get("timestamp")
                if isinstance(t, str):
                    try:
                        t = int(pd.to_datetime(t).timestamp())
                    except Exception:
                        t = int(time.time())
                formatted.append({
                    "time": int(t),
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": float(b["close"]),
                    "volume": float(b.get("volume", b.get("tick_volume", 0)))
                })
            return formatted

        # Fallback to PaperTradingBroker
        df = self._paper_broker.get_market_data(symbol=symbol.upper(), timeframe=timeframe.upper(), bars=100)
        formatted = []
        for idx, row in df.iterrows():
            if isinstance(idx, pd.Timestamp):
                t = int(idx.timestamp())
            else:
                t = int(pd.to_datetime(row.get("timestamp", time.time())).timestamp())
            formatted.append({
                "time": t,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0))
            })
        return formatted

    def get_bars_payload(self, symbol: str, timeframe: str = "M5") -> Dict[str, Any]:
        return {
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "bars": self.get_bars_list(symbol, timeframe)
        }

    def get_open_positions(self) -> List[Dict[str, Any]]:
        if self._mt5_state and self._mt5_state.get("connected"):
            return self._mt5_state.get("open_positions", [])
        return self._paper_broker.get_open_positions()

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        if self._mt5_state and self._mt5_state.get("connected"):
            return self._mt5_state.get("closed_orders", [])
        return self._paper_broker.get_closed_orders()

    def get_specialist_status(self) -> Dict[str, Any]:
        return {
            "gold": {
                "name": "GoldSpecialistAgent",
                "symbol": "XAUUSD",
                "strategy": "MTF Momentum Cross",
                "status": "ACTIVE"
            },
            "btc": {
                "name": "BtcSpecialistAgent",
                "symbol": "BTCUSD",
                "strategy": "EMA Pullback Rejection",
                "status": "ACTIVE"
            },
            "eth": {
                "name": "EthSpecialistAgent",
                "symbol": "ETHUSD",
                "strategy": "Bollinger Bands Reversion",
                "status": "ACTIVE"
            }
        }

    def get_snapshot(self, symbol: str = "XAUUSD", timeframe: str = "M5") -> Dict[str, Any]:
        return {
            "type": "snapshot",
            "account": self.get_account_data(),
            "portfolio": self.get_portfolio_metrics(),
            "symbol": symbol.upper(),
            "timeframe": timeframe.upper(),
            "bars": self.get_bars_list(symbol, timeframe),
            "open_positions": self.get_open_positions(),
            "closed_orders": self.get_closed_orders(),
            "specialists": self.get_specialist_status()
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_frontend_feed.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/__init__.py frontend/feed_provider.py tests/test_frontend_feed.py
git commit -m "feat(frontend): implement dual-mode DashboardFeedProvider with tests"
```

---

### Task 2: WebSocket Hub & FastAPI Router (`frontend/router.py`)

**Files:**
- Create: `frontend/router.py`
- Modify: `mt5/bridge_server.py`
- Test: `tests/test_frontend_router.py`

**Interfaces:**
- Consumes: `DashboardFeedProvider`
- Produces: `frontend_router: APIRouter`
- Produces: `mount_frontend(app: FastAPI)`
- Produces: `ws_hub.broadcast(message: Dict[str, Any])`

- [ ] **Step 1: Write the failing test for `frontend/router.py`**

```python
# tests/test_frontend_router.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from frontend.router import frontend_router, mount_frontend, ws_hub

def test_frontend_mount_and_index():
    app = FastAPI()
    mount_frontend(app)
    client = TestClient(app)
    
    # Test health/snapshot api
    res = client.get("/api/dashboard/snapshot?symbol=XAUUSD&timeframe=M5")
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "snapshot"
    assert "account" in data

def test_websocket_connection_and_subscription():
    app = FastAPI()
    mount_frontend(app)
    client = TestClient(app)
    
    with client.websocket_connect("/ws/live") as websocket:
        # First message should be initial snapshot
        init_data = websocket.receive_json()
        assert init_data["type"] == "snapshot"
        assert init_data["symbol"] == "XAUUSD"
        
        # Send subscription request for BTCUSD M15
        websocket.send_json({"action": "subscribe", "symbol": "BTCUSD", "timeframe": "M15"})
        resp = websocket.receive_json()
        assert resp["type"] == "bars"
        assert resp["symbol"] == "BTCUSD"
        assert resp["timeframe"] == "M15"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_frontend_router.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'frontend.router'`

- [ ] **Step 3: Implement `frontend/router.py` and mount in `mt5/bridge_server.py`**

```python
# frontend/router.py
"""FastAPI Router and WebSocket Hub for the Real-time Dashboard."""
from typing import Set, Dict, Any, Optional
import json
import logging
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, FastAPI, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from frontend.feed_provider import DashboardFeedProvider

logger = logging.getLogger("frontend_router")

class WebSocketHub:
    """Manages active WebSocket connections and broadcasts real-time events."""
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"[WebSocketHub] Client connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"[WebSocketHub] Client disconnected. Total active: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        if not self.active_connections:
            return
        dead_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                dead_connections.add(connection)
        for dead in dead_connections:
            self.active_connections.discard(dead)

ws_hub = WebSocketHub()
frontend_router = APIRouter()
_feed_provider: Optional[DashboardFeedProvider] = None

def get_feed_provider() -> DashboardFeedProvider:
    global _feed_provider
    if _feed_provider is None:
        _feed_provider = DashboardFeedProvider()
    return _feed_provider

def set_feed_provider(provider: DashboardFeedProvider):
    global _feed_provider
    _feed_provider = provider

@frontend_router.get("/api/dashboard/snapshot")
async def get_dashboard_snapshot(symbol: str = Query("XAUUSD"), timeframe: str = Query("M5")):
    provider = get_feed_provider()
    return provider.get_snapshot(symbol=symbol, timeframe=timeframe)

@frontend_router.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await ws_hub.connect(websocket)
    provider = get_feed_provider()
    current_symbol = "XAUUSD"
    current_tf = "M5"
    try:
        # Send initial snapshot
        snapshot = provider.get_snapshot(symbol=current_symbol, timeframe=current_tf)
        await websocket.send_json(snapshot)
        
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "subscribe":
                current_symbol = data.get("symbol", current_symbol).upper()
                current_tf = data.get("timeframe", current_tf).upper()
                bars_payload = provider.get_bars_payload(current_symbol, current_tf)
                await websocket.send_json({
                    "type": "bars",
                    **bars_payload
                })
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_hub.disconnect(websocket)
    except Exception as exc:
        logger.error(f"[WebSocketLive] Error: {exc}")
        ws_hub.disconnect(websocket)

def mount_frontend(app: FastAPI, mt5_state_ref: Optional[Dict[str, Any]] = None, cached_bars_ref: Optional[Dict[str, Any]] = None):
    """Mounts frontend routes and static directory."""
    if mt5_state_ref is not None or cached_bars_ref is not None:
        set_feed_provider(DashboardFeedProvider(mt5_state_ref=mt5_state_ref, cached_bars_ref=cached_bars_ref))
    
    app.include_router(frontend_router)
    
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    
    @app.get("/", include_in_schema=False)
    async def serve_index():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return {"status": "Frontend initialized. Static index.html loading..."}

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
```

Now update `mt5/bridge_server.py` to call `mount_frontend(app, _mt5_state, _cached_bars)` and broadcast on telemetry/bars.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_frontend_router.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/router.py tests/test_frontend_router.py mt5/bridge_server.py
git commit -m "feat(frontend): implement WebSocket hub and mount frontend router onto bridge server"
```

---

### Task 3: HTML & Dark Terminal Theme (`frontend/static/index.html` & `frontend/static/css/terminal.css`)

**Files:**
- Create: `frontend/static/index.html`
- Create: `frontend/static/css/terminal.css`

- [ ] **Step 1: Create `frontend/static/css/terminal.css`**
  - Implement high-contrast dark Bloomberg/TradingView terminal styles.
  - Implement glowing status badges (`pulse-green`, `pulse-yellow`, `pulse-red`).
  - Implement sleek progress bars with markers for +3.0% Soft Target, +10.0% Hard Target, and -3.0% Max Loss.
  - Implement scrollable position tables and event history feeds with monospace font styling.

- [ ] **Step 2: Create `frontend/static/index.html`**
  - Include Tailwind CSS CDN (`https://cdn.tailwindcss.com`) and TradingView Lightweight Charts CDN (`https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js`).
  - Render Top Header (Brand, Mode Badge, Connection Status with Ping, UTC clock).
  - Render Account KPI cards (Balance, Equity, Floating PnL, Today PnL).
  - Render Daily Target Progress Bar card.
  - Render Main Grid:
    - Left Column: Symbol & Timeframe selectors, Candlestick Chart container (`#tv-chart`), Open Positions Table.
    - Right Column: Specialist Squad Monitor cards, Closed Orders Today Feed.
  - Link `css/terminal.css`, `js/chart.js`, and `js/dashboard.js`.

- [ ] **Step 3: Verify static files via HTTP test**

Run: `pytest tests/test_frontend_router.py -k test_frontend_mount_and_index -v`  
Expected: PASS and verifies HTML content is served at `/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/static/index.html frontend/static/css/terminal.css
git commit -m "feat(frontend): create dark terminal HTML5 layout and custom CSS styling"
```

---

### Task 4: TradingView Candlestick Chart Module (`frontend/static/js/chart.js`)

**Files:**
- Create: `frontend/static/js/chart.js`

- [ ] **Step 1: Implement `frontend/static/js/chart.js`**
  - Create and configure TradingView Lightweight Chart instance with dark theme:
    - Background: `#0B0F19`, Gridlines: `#1E293B`, Text: `#94A3B8`.
    - Bullish candles: `#10B981`, Bearish candles: `#EF4444`.
  - Add Candlestick series and Volume histogram series.
  - Support functions:
    - `initChart(containerId: string)`
    - `setCandles(bars: Array)`: Populate historical bars.
    - `updateLastCandle(bar: Object)`: Real-time update of current forming candle.
    - `renderTradeLines(positions: Array)`: Draw visual horizontal price lines on chart for entry price, red dashed line for SL, and green dashed line for TP.
    - `handleResize()`: Window resize listener for responsive charting.

- [ ] **Step 2: Syntax and module check**

Run: `node -c frontend/static/js/chart.js || python3 -c "import pathlib; assert pathlib.Path('frontend/static/js/chart.js').exists()"`  
Expected: Valid JavaScript syntax.

- [ ] **Step 3: Commit**

```bash
git add frontend/static/js/chart.js
git commit -m "feat(frontend): implement TradingView Lightweight Charts candlestick module with trade overlay"
```

---

### Task 5: Reactive WebSocket Client & DOM Updater (`frontend/static/js/dashboard.js`)

**Files:**
- Create: `frontend/static/js/dashboard.js`

- [ ] **Step 1: Implement `frontend/static/js/dashboard.js`**
  - Establish WebSocket connection to `ws://${window.location.host}/ws/live`.
  - Implement auto-reconnect with exponential backoff (1s to 5s).
  - Manage state: `currentSymbol`, `currentTimeframe`, `accountState`, `openPositions`, `closedOrders`.
  - Handle incoming messages:
    - `snapshot`: Update all KPI cards, progress bar, positions table, closed orders, specialist squad cards, and call `chart.setCandles()`.
    - `bars`: Call `chart.setCandles()`.
    - `telemetry` / `tick`: Update account numbers and floating PnL with green/red flash effects.
  - Bind UI event listeners:
    - Symbol buttons: `XAUUSD`, `BTCUSD`, `ETHUSD`, `EURUSD`, `GBPUSD` -> sends `{"action": "subscribe", "symbol": sym, "timeframe": tf}`.
    - Timeframe buttons: `M1`, `M5`, `M15`, `H1` -> sends `{"action": "subscribe", "symbol": sym, "timeframe": tf}`.
  - Render Functions:
    - `updateKpiCards(account, portfolio)`
    - `updateTargetProgressBar(portfolio)`
    - `renderPositionsTable(positions)`
    - `renderClosedOrders(orders)`
    - `renderSpecialistCards(specialists)`

- [ ] **Step 2: Commit**

```bash
git add frontend/static/js/dashboard.js
git commit -m "feat(frontend): implement reactive dashboard WebSocket client and DOM updater"
```

---

### Task 6: CLI Integration, Broadcast Hook & End-to-End Verification

**Files:**
- Modify: `main.py`
- Modify: `mt5/bridge_server.py`
- Test: `tests/test_frontend_e2e.py`

- [ ] **Step 1: Update `mt5/bridge_server.py` broadcast hooks**
  - When `receive_telemetry` receives payload from MT5 EA, trigger `asyncio.create_task(ws_hub.broadcast(...))`.
  - When `receive_bars` receives new bars from MT5 EA, trigger `asyncio.create_task(ws_hub.broadcast(...))`.

- [ ] **Step 2: Update `main.py` CLI banners**
  - In `cmd_bridge`: print prominent dashboard URL `http://127.0.0.1:8000`.
  - In `cmd_loop` (`main.py run`): add `--web` argument to optionally spin up the bridge server in background so user can watch the dashboard while running live trading loop.

- [ ] **Step 3: Write and run end-to-end integration test (`tests/test_frontend_e2e.py`)**

```python
# tests/test_frontend_e2e.py
import pytest
from fastapi.testclient import TestClient
from mt5.bridge_server import app

def test_full_bridge_dashboard_lifecycle():
    client = TestClient(app)
    
    # 1. Test index page returns 200 and loads HTML
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PILOTFISH QUANT TERMINAL" in resp.text
    
    # 2. Test WebSocket connection receives snapshot and responds to subscription
    with client.websocket_connect("/ws/live") as ws:
        snapshot = ws.receive_json()
        assert snapshot["type"] == "snapshot"
        assert "account" in snapshot
        assert "bars" in snapshot
        
        # Subscribe to ETHUSD
        ws.send_json({"action": "subscribe", "symbol": "ETHUSD", "timeframe": "M5"})
        bars_msg = ws.receive_json()
        assert bars_msg["type"] == "bars"
        assert bars_msg["symbol"] == "ETHUSD"
```

- [ ] **Step 4: Run full test suite to verify everything passes**

Run: `pytest tests/test_frontend*.py -v`  
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add main.py mt5/bridge_server.py tests/test_frontend_e2e.py
git commit -m "feat(frontend): integrate live telemetry broadcast hooks, CLI dashboard URLs, and E2E tests"
```
