"""
FastAPI Server and Client Bridge for MetaTrader 5 (MT5).
Enables bidirectional communication between Python and MT5 via AgenticMT5Bridge.mq5.
"""

from typing import Dict, Any, List, Optional
import asyncio
import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pandas as pd
import logging
from time import time as monotonic_wall_time
from config import config
from mt5.broker_interface import BaseBroker
from frontend.router import mount_frontend, ws_hub, get_feed_provider

logger = logging.getLogger("mt5_bridge_server")

app = FastAPI(title="MT5 Agentic Bridge API", version="2.0.0")

KNOWN_CANONICAL_SYMBOLS = {
    "XAUUSD", "BTCUSD", "ETHUSD", "XAGUSD", "GBPUSD", "EURUSD", "XPTUSD", "UKOIL", "XNGUSD"
}


def normalize_symbol(symbol: str) -> str:
    """Strip common broker suffixes (.m, _i, .c, m, c, pro, raw, etc.) to canonical name."""
    if not isinstance(symbol, str):
        return str(symbol)
    s = symbol.strip().upper()
    if s in KNOWN_CANONICAL_SYMBOLS:
        return s

    # Check if symbol starts with any known canonical symbol
    for canon in sorted(KNOWN_CANONICAL_SYMBOLS, key=len, reverse=True):
        if s.startswith(canon):
            suffix = s[len(canon):]
            if suffix in ("", "M", "C", ".M", ".C", "_I", ".PRO", "PRO", ".RAW", "RAW"):
                return canon

    # Fallback: strip common punctuation/trailing characters if any
    for suff in [".M", ".C", "_I", ".PRO", ".RAW", "M", "C"]:
        if s.endswith(suff) and len(s) > len(suff):
            return s[:-len(suff)]
    return s


def canonical_symbol_key(symbol: str, timeframe: str) -> str:
    """Return unified symbol:timeframe key, e.g. XAUUSD:M5."""
    return f"{normalize_symbol(symbol)}:{timeframe.strip().upper()}"


@app.middleware("http")
async def strip_mql5_json_terminator(request: Request, call_next):
    """Accept MQL5's optional trailing NUL without relaxing JSON validation."""
    if request.headers.get("content-type", "").startswith("application/json"):
        raw_body = await request.body()
        clean_body = raw_body.rstrip(b"\x00")
        if clean_body != raw_body:
            request._body = clean_body

            async def receive():
                return {"type": "http.request", "body": clean_body, "more_body": False}

            request._receive = receive
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def log_validation_error(request: Request, exc: RequestValidationError):
    """Expose malformed EA telemetry in bridge logs instead of a bare HTTP 422."""
    raw_body = await request.body()
    logger.error(
        "[MT5-VALIDATION] %s %s rejected: errors=%s body=%s",
        request.method,
        request.url.path,
        exc.errors(),
        raw_body.decode("utf-8", errors="replace")[:2000],
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

# In-Memory Bridge State
_mt5_state = {
    "account_number": config.mt5_login,
    "server": config.mt5_server,
    "balance": 10000.0,
    "equity": 10000.0,
    "symbol": "XAUUSD",
    "bid": 2650.0,
    "ask": 2650.25,
    "open_positions": [],
    "closed_orders": [],
    "recently_closed": [],
    "last_sync": "",
    "connected": False,
    "currency": "USD",
    "is_cent": False,
}
_pending_commands: List[Dict[str, Any]] = []
_execution_results: Dict[str, Any] = {}
# Bars are keyed by symbol/timeframe.  A single global frame can silently make
# BTC/ETH agents trade using XAUUSD candles, so never share it across markets.
_cached_bars: Dict[str, Dict[str, Any]] = {}
MARKET_DATA_MAX_AGE_SEC = 90.0
MAX_EXECUTION_RESULTS = 1_000

# Mount real-time frontend dashboard router & static assets
mount_frontend(app, _mt5_state, _cached_bars)


class MarketDataStale(RuntimeError):
    """Bars stopped changing: market closed or feed frozen."""


class TelemetryPayload(BaseModel):
    account_number: int
    server: Optional[str] = "Exness-MT5Trial14"
    balance: float
    equity: float
    symbol: str
    bid: float
    ask: float
    open_positions: List[Dict[str, Any]] = []
    closed_orders: List[Dict[str, Any]] = []
    currency: Optional[str] = "USD"
    is_cent: Optional[bool] = False


class ConfirmPayload(BaseModel):
    command_id: str
    status: str
    ticket: Optional[int] = None
    retcode: Optional[int] = None
    message: Optional[str] = ""


class BarsPayload(BaseModel):
    symbol: str
    timeframe: str
    bars: List[Dict[str, Any]]


def _validate_command(command: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the small, explicit command protocol accepted by the EA.

    The bridge is a trade boundary.  Accepting an arbitrary JSON object here
    would otherwise let a malformed request reach the EA and be interpreted as
    a SELL, or create an unprotected live position.  This validation is shared
    by REST and TestClient/in-process use so their behaviour cannot drift.
    """
    if not isinstance(command, dict):
        raise ValueError("command must be a JSON object")

    command_id = command.get("id")
    action = command.get("action")
    if not isinstance(command_id, str) or not command_id.strip():
        raise ValueError("id must be a non-empty string")
    if action not in {"ORDER_OPEN", "ORDER_CLOSE", "ORDER_MODIFY"}:
        raise ValueError("action must be ORDER_OPEN, ORDER_CLOSE, or ORDER_MODIFY")

    if action == "ORDER_OPEN":
        if not isinstance(command.get("symbol"), str) or not command["symbol"].strip():
            raise ValueError("ORDER_OPEN requires a non-empty symbol")
        if command.get("type") not in {"BUY", "SELL"}:
            raise ValueError("ORDER_OPEN type must be BUY or SELL")
        for field in ("volume", "sl", "tp"):
            value = command.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"ORDER_OPEN {field} must be a positive number")
    elif action == "ORDER_CLOSE":
        ticket = command.get("ticket")
        if not isinstance(ticket, int) or isinstance(ticket, bool) or ticket <= 0:
            raise ValueError("ORDER_CLOSE ticket must be a positive integer")
    else:
        ticket = command.get("ticket")
        if not isinstance(ticket, int) or isinstance(ticket, bool) or ticket <= 0:
            raise ValueError("ORDER_MODIFY ticket must be a positive integer")
        if not any(
            isinstance(command.get(field), (int, float))
            and not isinstance(command.get(field), bool)
            and command[field] > 0
            for field in ("sl", "tp")
        ):
            raise ValueError("ORDER_MODIFY requires a positive sl or tp")
    return command


@app.get("/api/mt5/status")
async def get_bridge_status():
    """Health check returning MT5 connection and account state."""
    now = monotonic_wall_time()
    market_data = {}
    for key, value in _cached_bars.items():
        sym_part = key.split(":")[0] if ":" in key else key
        canon_sym = normalize_symbol(sym_part)
        tf_part = key.split(":")[1] if ":" in key else "M5"
        canon_key = f"{canon_sym}:{tf_part}"
        if canon_key not in market_data:
            market_data[canon_key] = {
                "bars": len(value["bars"]),
                "age_sec": round(max(0.0, now - float(value["received_at"])), 1),
                "fresh": (now - float(value["received_at"])) <= MARKET_DATA_MAX_AGE_SEC,
            }
    return {
        "status": "ONLINE",
        "connected": _mt5_state["connected"],
        "account_number": _mt5_state["account_number"],
        "server": _mt5_state["server"],
        "balance": _mt5_state["balance"],
        "equity": _mt5_state["equity"],
        "currency": _mt5_state.get("currency", "USD"),
        "is_cent": _mt5_state.get("is_cent", False),
        "last_sync": _mt5_state["last_sync"],
        "market_data": market_data,
    }


@app.post("/api/mt5/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    """Called by MT5 EA to report live account, prices, positions, and history."""
    global _mt5_state
    _mt5_state["account_number"] = payload.account_number
    _mt5_state["server"] = payload.server or config.mt5_server
    _mt5_state["balance"] = payload.balance
    _mt5_state["equity"] = payload.equity
    _mt5_state["symbol"] = payload.symbol
    _mt5_state["bid"] = payload.bid
    _mt5_state["ask"] = payload.ask
    _mt5_state["open_positions"] = payload.open_positions
    _mt5_state["connected"] = True
    _mt5_state["currency"] = payload.currency or ("USC" if "cent" in (payload.server or "").lower() else "USD")
    _mt5_state["is_cent"] = bool(payload.is_cent or _mt5_state["currency"] == "USC")
    # Store an explicit UTC heartbeat.  Local timestamps (e.g. Asia/Bangkok)
    # otherwise look seven hours in the future to the live safety gate.
    _mt5_state["last_sync"] = pd.Timestamp.now(tz="UTC").isoformat()
    
    # Track newly closed orders
    if payload.closed_orders:
        for order in payload.closed_orders:
            if order not in _mt5_state["closed_orders"]:
                _mt5_state["closed_orders"].append(order)
                _mt5_state["recently_closed"].append(order)

    # Broadcast telemetry update to connected WebSocket clients
    try:
        portfolio_metrics = {}
        try:
            portfolio_metrics = get_feed_provider().get_portfolio_metrics()
        except Exception:
            pass

        asyncio.create_task(ws_hub.broadcast({
            "type": "telemetry",
            "account": {
                "account_number": _mt5_state["account_number"],
                "server": _mt5_state["server"],
                "mode": "MT5 LIVE",
                "balance": _mt5_state["balance"],
                "equity": _mt5_state["equity"],
                "bid": _mt5_state["bid"],
                "ask": _mt5_state["ask"],
                "symbol": _mt5_state["symbol"],
                "open_positions": _mt5_state["open_positions"],
                "closed_orders": _mt5_state["closed_orders"],
                "last_sync": _mt5_state["last_sync"],
                "connected": _mt5_state["connected"],
            },
            "portfolio": portfolio_metrics,
            "open_positions": _mt5_state["open_positions"],
            "closed_orders": _mt5_state["closed_orders"],
        }))
    except Exception as exc:
        logger.debug(f"[MT5-TELEMETRY] Broadcast error: {exc}")

    return {"status": "ACK", "server_time": _mt5_state["last_sync"]}


@app.get("/api/mt5/commands")
async def poll_commands():
    """Deliver exactly one FIFO command per EA poll.

    The EA protocol consumes one command envelope.  Returning and clearing a
    whole batch caused every command after the first to disappear without ever
    reaching MetaTrader.  Keeping the rest in the queue makes batched agent
    dispatch deterministic and backwards compatible with older EA builds.
    """
    command = _pending_commands.pop(0) if _pending_commands else None
    return {"commands": [command] if command is not None else []}


@app.post("/api/mt5/confirm")
async def confirm_execution(payload: ConfirmPayload):
    """Called by MT5 EA to confirm MQL5 trade result."""
    _execution_results[payload.command_id] = payload.model_dump()
    while len(_execution_results) > MAX_EXECUTION_RESULTS:
        _execution_results.pop(next(iter(_execution_results)))
    logger.info(f"[MT5-CONFIRM] Command {payload.command_id}: status={payload.status}, ticket=#{payload.ticket}")
    return {"status": "RECORDED"}


@app.get("/api/mt5/execution_results")
async def get_execution_result(command_id: str):
    """
    Returns the EA's confirmation for a command, or null if not yet confirmed.

    Consumed by MT5BridgeBroker._await_confirmation() so callers can distinguish
    "EA accepted and filled this" from "we queued it and hoped".
    """
    return {"command_id": command_id, "result": _execution_results.get(command_id)}


@app.post("/api/mt5/bars")
async def receive_bars(payload: BarsPayload):
    """Called by MT5 to upload latest bars."""
    global _cached_bars
    canon_sym = normalize_symbol(payload.symbol)
    tf = payload.timeframe.upper()
    canon_key = f"{canon_sym}:{tf}"
    raw_key = f"{payload.symbol.upper()}:{tf}"
    now = monotonic_wall_time()

    last = payload.bars[-1] if payload.bars else None
    prev = _cached_bars.get(canon_key) or _cached_bars.get(raw_key)
    moved = prev is None or not prev["bars"] or last is None or any(
        prev["bars"][-1].get(k) != last.get(k) for k in ("timestamp", "close", "volume"))
    entry = {
        "bars": payload.bars,
        "received_at": now,
        "changed_at": now if moved else prev["changed_at"],
        "broker_symbol": payload.symbol,
    }
    _cached_bars[canon_key] = entry
    if raw_key != canon_key:
        _cached_bars[raw_key] = entry

    # Broadcast bar update to connected WebSocket clients
    try:
        try:
            bars_to_send = get_feed_provider().get_bars_list(payload.symbol, payload.timeframe) or payload.bars
        except Exception:
            bars_to_send = payload.bars

        asyncio.create_task(ws_hub.broadcast({
            "type": "bars",
            "symbol": canon_sym,
            "broker_symbol": payload.symbol.upper(),
            "timeframe": tf,
            "bars": bars_to_send,
        }))
    except Exception as exc:
        logger.debug(f"[MT5-BARS] Broadcast error: {exc}")

    return {"status": "BARS_STORED", "count": len(payload.bars), "key": canon_key}


@app.get("/api/mt5/bars")
async def get_bars(symbol: str, timeframe: str = "M15"):
    """Serve the latest symbol-scoped bars to an agent in another process."""
    canon_key = canonical_symbol_key(symbol, timeframe)
    raw_key = f"{symbol.upper()}:{timeframe.upper()}"
    cached = _cached_bars.get(canon_key) or _cached_bars.get(raw_key)
    if cached is None:
        return {"symbol": normalize_symbol(symbol), "timeframe": timeframe.upper(), "bars": [], "received_at": None}
    return {
        "symbol": normalize_symbol(symbol),
        "broker_symbol": cached.get("broker_symbol", symbol),
        "timeframe": timeframe.upper(),
        "bars": cached["bars"],
        "received_at": cached["received_at"],
        "changed_at": cached.get("changed_at", cached["received_at"]),
    }


@app.get("/api/mt5/account")
async def get_account_state():
    """Returns live account state for client brokers."""
    return {
        "account_number": _mt5_state["account_number"],
        "server": _mt5_state["server"],
        "balance": _mt5_state["balance"],
        "equity": _mt5_state["equity"],
        "bid": _mt5_state["bid"],
        "ask": _mt5_state["ask"],
        "symbol": _mt5_state["symbol"],
        "connected": _mt5_state["connected"],
        "last_sync": _mt5_state["last_sync"],
        "open_positions": _mt5_state["open_positions"],
        "closed_orders": _mt5_state["closed_orders"]
    }


@app.get("/api/mt5/recently_closed")
async def get_recently_closed(symbol: Optional[str] = None, magic: Optional[int] = None):
    """Returns and clears recently closed orders (only `symbol`'s / `magic`'s when given)."""
    return {"recently_closed": _pop_recently_closed(symbol, magic)}


def _pop_recently_closed(symbol: Optional[str], magic: Optional[int] = None) -> List[Dict[str, Any]]:
    queue = _mt5_state["recently_closed"]
    taken = [
        o for o in queue
        if (not symbol or str(o.get("symbol", "")).upper() == symbol.upper())
        and (magic is None or o.get("magic", 888999) == magic)
    ]
    kept = [o for o in queue if o not in taken]
    queue[:] = kept
    return taken


@app.post("/api/mt5/queue_command")
async def queue_command_endpoint(command: Dict[str, Any]):
    """Receives commands from external client processes."""
    try:
        _validate_command(command)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _pending_commands.append(command)
    logger.info(f"[MT5-QUEUE] Queued via REST: {command.get('action')} {command.get('volume')} lots on {command.get('symbol')}")
    return {"status": "QUEUED", "command_id": command.get("id")}


class MT5BridgeBroker(BaseBroker):
    """Python broker adapter communicating with MetaTrader 5."""

    def __init__(self, host: str = None, port: int = None, in_process: bool = False):
        """
        `in_process=True` reads/writes this module's own state dicts directly
        instead of going over REST. Only valid when the bridge app runs in the
        SAME process (e.g. FastAPI TestClient). Production runs bridge and agent
        in separate containers, where those dicts are unreachable — hence REST
        by default.
        """
        self.host = host or config.mt5_host
        self.port = port or config.mt5_port
        self.base_url = f"http://{self.host}:{self.port}"
        self.in_process = in_process
        self.cmd_counter = 1
        # Short random suffix so IDs stay unique even across broker instances,
        # processes and restarts. A per-instance counter + 1-second timestamp
        # collides when two brokers issue a command within the same second,
        # which made the bridge return order A's confirmation for order B.
        self.cmd_namespace = uuid.uuid4().hex[:8]

        # 0.0.0.0 is a *server bind* address, not a valid client target.  The
        # compose `bridge` service sets MT5_HOST=0.0.0.0 so uvicorn binds all
        # interfaces, and the `squad` service sets MT5_HOST=bridge so it can
        # reach it.  If either default leaks through unchanged (bare
        # `python3 main.py run --mode=mt5` on the Docker host, or a compose
        # service that forgot to set MT5_HOST), this client would otherwise
        # try to connect to http://0.0.0.0:8000 and fail confusingly.  Pin the
        # client default to loopback, which is correct whenever the bridge
        # process runs on the same host (native Windows or Docker Desktop).
        if not self.in_process and self.host in ("0.0.0.0", ""):
            self.host = "127.0.0.1"
            self.base_url = f"http://{self.host}:{self.port}"
            logger.info(
                "[MT5-BROKER] MT5_HOST was %r; treating it as the server bind "
                "address and connecting via loopback http://127.0.0.1:%s instead. "
                "If the bridge runs in another container/host, set MT5_HOST to "
                "its DNS name or LAN IP.",
                config.mt5_host,
                self.port,
            )

    def _next_cmd_id(self, kind: str) -> str:
        """Builds a collision-free command id: cmd_<ns>_<kind>_<n>_<ts>."""
        cmd_id = f"cmd_{self.cmd_namespace}_{kind}_{self.cmd_counter}_{int(time.time())}"
        self.cmd_counter += 1
        return cmd_id

    def _queue_command(self, command: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        """
        Delivers a command to the bridge and returns its response. Raises
        RuntimeError if the bridge is unreachable or rejects it.

        Deliberately does NOT swallow exceptions: a silently swallowed error here
        means the caller believes an order was placed when it never left the
        process. That exact failure mode hid a missing `import httpx` for hours.
        """
        if self.in_process:
            try:
                _validate_command(command)
            except ValueError as exc:
                raise RuntimeError(
                    f"[MT5-QUEUE] Bridge rejected command {command.get('id')}: {exc}"
                ) from exc
            _pending_commands.append(command)
            logger.info(
                f"[MT5-QUEUE] Queued in-process: {command.get('action')} "
                f"{command.get('volume')} lots on {command.get('symbol')}"
            )
            return {"status": "QUEUED", "command_id": command.get("id")}

        url = f"{self.base_url}/api/mt5/queue_command"
        try:
            resp = httpx.post(url, json=command, timeout=timeout)
        except Exception as e:
            raise RuntimeError(
                f"[MT5-QUEUE] Cannot reach MT5 bridge at {self.base_url} "
                f"({type(e).__name__}: {e}). Command {command.get('id')} was NOT queued."
            ) from e

        if resp.status_code != 200:
            raise RuntimeError(
                f"[MT5-QUEUE] Bridge rejected command {command.get('id')}: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        return resp.json()

    def _await_confirmation(
        self,
        cmd_id: str,
        timeout: float = 10.0,
        poll_interval: float = 0.25
    ) -> Optional[Dict[str, Any]]:
        """
        Polls the bridge until the EA confirms execution of `cmd_id`.

        Returns the confirmation dict on success, or None on timeout. A timeout
        is NOT proof of failure (the EA may simply not be attached), so callers
        should treat None as "unconfirmed" rather than "rejected".
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.in_process:
                result = _execution_results.get(cmd_id)
                if result:
                    return result
            else:
                try:
                    resp = httpx.get(
                        f"{self.base_url}/api/mt5/execution_results",
                        params={"command_id": cmd_id},
                        timeout=5.0
                    )
                    if resp.status_code == 200:
                        result = resp.json().get("result")
                        if result:
                            return result
                except Exception as e:
                    logger.warning(f"[MT5-CONFIRM] Poll failed for {cmd_id}: {type(e).__name__}: {e}")
            time.sleep(poll_interval)
        return None

    def get_account_info(self) -> Dict[str, Any]:
        """Returns account telemetry reported by MT5 terminal."""
        if not self.in_process:
            try:
                resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
                if resp.status_code == 200:
                    data = resp.json()
                    data["open_positions_count"] = len(data.get("open_positions", []))
                    return data
            except Exception as e:
                logger.warning(
                    f"[MT5-ACCOUNT] Bridge unreachable at {self.base_url} "
                    f"({type(e).__name__}: {e}); returning last-known in-process state."
                )

        return {
            "account_number": _mt5_state["account_number"],
            "server": _mt5_state["server"],
            "balance": _mt5_state["balance"],
            "equity": _mt5_state["equity"],
            "bid": _mt5_state["bid"],
            "ask": _mt5_state["ask"],
            "symbol": _mt5_state["symbol"],
            "connected": _mt5_state["connected"],
            "open_positions_count": len(_mt5_state["open_positions"])
        }

    def _detect_broker_suffix(self) -> str:
        """Detect active broker symbol suffix (e.g. 'm', 'c') from MT5 telemetry symbol."""
        if hasattr(self, "_broker_suffix"):
            return self._broker_suffix
        self._broker_suffix = ""
        try:
            telemetry_sym = ""
            if self.in_process:
                telemetry_sym = _mt5_state.get("symbol", "")
            else:
                resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=2.0)
                if resp.status_code == 200:
                    telemetry_sym = resp.json().get("symbol", "")
            if telemetry_sym:
                norm = normalize_symbol(telemetry_sym)
                if telemetry_sym.upper().startswith(norm.upper()) and len(telemetry_sym) > len(norm):
                    self._broker_suffix = telemetry_sym[len(norm):]
        except Exception:
            pass
        return self._broker_suffix

    def _resolve_broker_symbol(self, symbol: str) -> str:
        """Resolve canonical symbol (e.g. XAUUSD) to active broker symbol (e.g. XAUUSDm)."""
        if not hasattr(self, "_broker_symbol_cache"):
            self._broker_symbol_cache = {}
        if symbol in self._broker_symbol_cache:
            return self._broker_symbol_cache[symbol]

        suffix = self._detect_broker_suffix()
        norm = normalize_symbol(symbol)
        if suffix and not symbol.endswith(suffix):
            resolved = f"{norm}{suffix}"
            self._broker_symbol_cache[symbol] = resolved
            return resolved

        norm_target = norm.upper()
        # 1. In-process: check cached bars or telemetry
        if self.in_process:
            for k, entry in _cached_bars.items():
                broker_sym = entry.get("broker_symbol")
                if broker_sym and normalize_symbol(broker_sym).upper() == norm_target:
                    self._broker_symbol_cache[symbol] = broker_sym
                    return broker_sym
                cand = k.split(":")[0]
                if normalize_symbol(cand).upper() == norm_target:
                    self._broker_symbol_cache[symbol] = cand
                    return cand
            telemetry_sym = _mt5_state.get("symbol")
            if telemetry_sym and normalize_symbol(telemetry_sym).upper() == norm_target:
                self._broker_symbol_cache[symbol] = telemetry_sym
                return telemetry_sym

        # 2. Over REST: check /api/mt5/status
        if not self.in_process:
            try:
                resp = httpx.get(f"{self.base_url}/api/mt5/status", timeout=2.0)
                if resp.status_code == 200:
                    data = resp.json()
                    for k in data.get("market_data", {}).keys():
                        cand = k.split(":")[0]
                        if normalize_symbol(cand).upper() == norm_target:
                            self._broker_symbol_cache[symbol] = cand
                            return cand
            except Exception:
                pass

        return symbol

    def get_market_data(self, symbol: str = "XAUUSD", timeframe: str = "M5", bars: int = 100) -> pd.DataFrame:
        """Return fresh MT5 bars; never substitute backtest data in live mode."""
        key = canonical_symbol_key(symbol, timeframe)
        raw_key = f"{symbol.upper()}:{timeframe.upper()}"
        broker_sym = self._resolve_broker_symbol(symbol)
        broker_raw_key = f"{broker_sym.upper()}:{timeframe.upper()}"
        if self.in_process:
            cached = _cached_bars.get(key) or _cached_bars.get(raw_key) or _cached_bars.get(broker_raw_key)
        else:
            try:
                response = httpx.get(
                    f"{self.base_url}/api/mt5/bars",
                    params={"symbol": symbol, "timeframe": timeframe},
                    timeout=3.0,
                )
                payload = response.json() if response.status_code == 200 else {}
                bars_list = payload.get("bars", [])

                if not bars_list and broker_sym != symbol:
                    response2 = httpx.get(
                        f"{self.base_url}/api/mt5/bars",
                        params={"symbol": broker_sym, "timeframe": timeframe},
                        timeout=3.0,
                    )
                    if response2.status_code == 200:
                        payload2 = response2.json()
                        if payload2.get("bars"):
                            payload = payload2

                cached = {
                    "bars": payload.get("bars", []),
                    "received_at": payload.get("received_at"),
                    "changed_at": payload.get("changed_at"),
                }
            except Exception as exc:
                raise RuntimeError(f"Live market data endpoint unavailable for {key}: {exc}") from exc
        if cached is None:
            raise RuntimeError(
                f"Live market data unavailable for {key}; refusing to use historical fallback. "
                "Check EA bar telemetry and WebRequest permissions."
            )
        if cached.get("received_at") is None:
            raise RuntimeError(
                f"Live market data unavailable for {key}; refusing to use historical fallback. "
                "Check EA bar telemetry and WebRequest permissions."
            )
        age = monotonic_wall_time() - float(cached.get("changed_at") or cached["received_at"])
        if age > MARKET_DATA_MAX_AGE_SEC:
            raise MarketDataStale(
                f"Live market data stale for {key} (no new tick for {age:.1f}s, limit {MARKET_DATA_MAX_AGE_SEC:.0f}s)."
            )
        df = pd.DataFrame(cached["bars"])
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            raise RuntimeError(f"Live bars for {key} missing columns: {sorted(required - set(df.columns))}")
        return df.tail(bars).copy().reset_index(drop=True)

    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = "",
        await_confirm: bool = True,
        confirm_timeout: float = 10.0,
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Queues an MQL5 trade order for the MT5 EA to execute.

        Raises RuntimeError if the command could not be delivered to the bridge.
        When await_confirm is True, blocks until the EA reports back (or timeout)
        so callers get a real fill status instead of a bare "QUEUED".
        """
        cmd_id = self._next_cmd_id("mt5")
        broker_sym = self._resolve_broker_symbol(symbol)

        command = {
            "id": cmd_id,
            "action": "ORDER_OPEN",
            "symbol": broker_sym,
            "type": order_type,
            "volume": lots,
            "sl": sl,
            "tp": tp,
            "comment": comment or f"AgenticMT5_{order_type}"
        }
        if magic is not None:
            command["magic"] = magic

        response = self._queue_command(command)
        logger.info(
            f"[MT5-QUEUE] Delivered to bridge: {order_type} {lots} lots on {symbol} "
            f"(SL: {sl:.2f}, TP: {tp:.2f}) cmd={cmd_id}"
        )

        if not await_confirm:
            return response

        confirmation = self._await_confirmation(cmd_id, timeout=confirm_timeout)
        if confirmation is None:
            logger.warning(
                f"[MT5-CONFIRM] No EA confirmation for {cmd_id} within {confirm_timeout}s. "
                f"Command is queued but unconfirmed — check that the EA is attached to a "
                f"chart and that WebRequest is allowed for {self.base_url}."
            )
            return {
                **response,
                "confirmed": False,
                "warning": "Queued but not confirmed by EA within timeout.",
            }

        status = confirmation.get("status")
        if status not in ("SUCCESS", "EXECUTED", "FILLED"):
            raise RuntimeError(
                f"[MT5-EXEC] EA rejected {cmd_id}: status={status}, "
                f"retcode={confirmation.get('retcode')}, message={confirmation.get('message')}"
            )

        logger.info(
            f"[MT5-EXEC] {cmd_id} filled: ticket=#{confirmation.get('ticket')} status={status}"
        )
        return {**response, "confirmed": True, "ticket": confirmation.get("ticket"), **confirmation}

    def close_order(
        self,
        ticket: int,
        await_confirm: bool = True,
        confirm_timeout: float = 10.0,
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """Queues a position close command for MT5 and waits for EA confirmation."""
        cmd_id = self._next_cmd_id("close")

        command = {
            "id": cmd_id,
            "action": "ORDER_CLOSE",
            "ticket": ticket
        }
        if magic is not None:
            command["magic"] = magic

        response = self._queue_command(command)

        if not await_confirm:
            return response

        confirmation = self._await_confirmation(cmd_id, timeout=confirm_timeout)
        if confirmation is None:
            logger.warning(f"[MT5-CONFIRM] No EA confirmation for close {cmd_id} within {confirm_timeout}s.")
            return {**response, "confirmed": False}
        status = confirmation.get("status")
        if status not in ("SUCCESS", "EXECUTED", "FILLED"):
            raise RuntimeError(
                f"[MT5-EXEC] EA rejected close {cmd_id}: status={status}, "
                f"retcode={confirmation.get('retcode')}, message={confirmation.get('message')}"
            )
        return {**response, "confirmed": True, **confirmation}

    def modify_order(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        await_confirm: bool = True,
        confirm_timeout: float = 10.0,
        magic: Optional[int] = None
    ) -> Dict[str, Any]:
        """Queues an order modification for MT5 and waits for EA confirmation."""
        cmd_id = self._next_cmd_id("modify")

        command = {
            "id": cmd_id,
            "action": "ORDER_MODIFY",
            "ticket": ticket,
            "sl": sl,
            "tp": tp
        }
        if magic is not None:
            command["magic"] = magic

        response = self._queue_command(command)

        if not await_confirm:
            return response

        confirmation = self._await_confirmation(cmd_id, timeout=confirm_timeout)
        if confirmation is None:
            logger.warning(f"[MT5-CONFIRM] No EA confirmation for modify {cmd_id} within {confirm_timeout}s.")
            return {**response, "confirmed": False}
        status = confirmation.get("status")
        if status not in ("SUCCESS", "EXECUTED", "FILLED"):
            raise RuntimeError(
                f"[MT5-EXEC] EA rejected modify {cmd_id}: status={status}, "
                f"retcode={confirmation.get('retcode')}, message={confirmation.get('message')}"
            )
        return {**response, "confirmed": True, **confirmation}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        if not self.in_process:
            try:
                resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
                if resp.status_code == 200:
                    return resp.json().get("open_positions", [])
            except Exception as e:
                logger.warning(f"[MT5-POSITIONS] Bridge unreachable ({type(e).__name__}: {e}); using in-process state.")
        return _mt5_state["open_positions"]

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        if not self.in_process:
            try:
                resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
                if resp.status_code == 200:
                    return resp.json().get("closed_orders", [])
            except Exception as e:
                logger.warning(f"[MT5-HISTORY] Bridge unreachable ({type(e).__name__}: {e}); using in-process state.")
        return _mt5_state["closed_orders"]

    def consume_recently_closed(self, symbol: Optional[str] = None, magic: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self.in_process:
            try:
                params = {}
                if symbol:
                    params["symbol"] = symbol
                if magic is not None:
                    params["magic"] = magic
                resp = httpx.get(
                    f"{self.base_url}/api/mt5/recently_closed",
                    params=params or None,
                    timeout=3.0,
                )
                if resp.status_code == 200:
                    return resp.json().get("recently_closed", [])
            except Exception as e:
                logger.warning(f"[MT5-RECENT] Bridge unreachable ({type(e).__name__}: {e}); using in-process state.")

        return _pop_recently_closed(symbol, magic)
