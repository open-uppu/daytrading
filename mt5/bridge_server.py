"""
FastAPI Server and Client Bridge for MetaTrader 5 (MT5).
Enables bidirectional communication between Python and MT5 via AgenticMT5Bridge.mq5.
"""

from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import logging
from config import config
from mt5.broker_interface import BaseBroker

logger = logging.getLogger("mt5_bridge_server")

app = FastAPI(title="MT5 Agentic Bridge API", version="2.0.0")

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
    "connected": False
}
_pending_commands: List[Dict[str, Any]] = []
_execution_results: Dict[str, Any] = {}
_cached_bars: List[Dict[str, Any]] = []


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


@app.get("/api/mt5/status")
async def get_bridge_status():
    """Health check returning MT5 connection and account state."""
    return {
        "status": "ONLINE",
        "connected": _mt5_state["connected"],
        "account_number": _mt5_state["account_number"],
        "server": _mt5_state["server"],
        "balance": _mt5_state["balance"],
        "equity": _mt5_state["equity"],
        "last_sync": _mt5_state["last_sync"]
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
    _mt5_state["last_sync"] = pd.Timestamp.now().isoformat()
    
    # Track newly closed orders
    if payload.closed_orders:
        for order in payload.closed_orders:
            if order not in _mt5_state["closed_orders"]:
                _mt5_state["closed_orders"].append(order)
                _mt5_state["recently_closed"].append(order)
                
    return {"status": "ACK", "server_time": _mt5_state["last_sync"]}


@app.get("/api/mt5/commands")
async def poll_commands():
    """Polled by MT5 EA to retrieve queued trade commands."""
    global _pending_commands
    commands = list(_pending_commands)
    _pending_commands.clear()
    return {"commands": commands}


@app.post("/api/mt5/confirm")
async def confirm_execution(payload: ConfirmPayload):
    """Called by MT5 EA to confirm MQL5 trade result."""
    _execution_results[payload.command_id] = payload.model_dump()
    logger.info(f"[MT5-CONFIRM] Command {payload.command_id}: status={payload.status}, ticket=#{payload.ticket}")
    return {"status": "RECORDED"}


@app.post("/api/mt5/bars")
async def receive_bars(payload: BarsPayload):
    """Called by MT5 to upload latest bars."""
    global _cached_bars
    _cached_bars = payload.bars
    return {"status": "BARS_STORED", "count": len(payload.bars)}


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
        "open_positions": _mt5_state["open_positions"],
        "closed_orders": _mt5_state["closed_orders"]
    }


@app.get("/api/mt5/recently_closed")
async def get_recently_closed():
    """Returns and clears recently closed orders."""
    recent = list(_mt5_state["recently_closed"])
    _mt5_state["recently_closed"].clear()
    return {"recently_closed": recent}


@app.post("/api/mt5/queue_command")
async def queue_command_endpoint(command: Dict[str, Any]):
    """Receives commands from external client processes."""
    _pending_commands.append(command)
    logger.info(f"[MT5-QUEUE] Queued via REST: {command.get('action')} {command.get('volume')} lots on {command.get('symbol')}")
    return {"status": "QUEUED", "command_id": command.get("id")}


class MT5BridgeBroker(BaseBroker):
    """Python broker adapter communicating with MetaTrader 5."""

    def __init__(self, host: str = None, port: int = None):
        self.host = host or config.mt5_host
        self.port = port or config.mt5_port
        self.base_url = f"http://{self.host}:{self.port}"
        self.cmd_counter = 1

    def get_account_info(self) -> Dict[str, Any]:
        """Returns account telemetry reported by MT5 terminal."""
        try:
            resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
            if resp.status_code == 200:
                data = resp.json()
                data["open_positions_count"] = len(data.get("open_positions", []))
                return data
        except Exception:
            pass

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

    def get_market_data(self, symbol: str = "XAUUSD", timeframe: str = "M15", bars: int = 100) -> pd.DataFrame:
        """Returns cached bars or transforms telemetry into DataFrame."""
        if _cached_bars:
            df = pd.DataFrame(_cached_bars)
            return df.tail(bars).copy().reset_index(drop=True)
            
        # Fallback to local cached historical data from data_loader
        from backtest.data_loader import load_historical_data
        df = load_historical_data(symbol=symbol, timeframe=timeframe)
        return df.tail(bars).copy().reset_index(drop=True)

    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = ""
    ) -> Dict[str, Any]:
        """Queues an MQL5 trade order for the MT5 EA to execute."""
        cmd_id = f"cmd_mt5_{self.cmd_counter}_{int(pd.Timestamp.now().timestamp())}"
        self.cmd_counter += 1
        
        command = {
            "id": cmd_id,
            "action": "ORDER_OPEN",
            "symbol": symbol,
            "type": order_type,
            "volume": lots,
            "sl": sl,
            "tp": tp,
            "comment": comment or f"AgenticMT5_{order_type}"
        }
        
        try:
            resp = httpx.post(f"{self.base_url}/api/mt5/queue_command", json=command, timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

        _pending_commands.append(command)
        logger.info(f"[MT5-QUEUE] Queued {order_type} {lots} lots on {symbol} (SL: {sl:.2f}, TP: {tp:.2f})")
        return {"status": "QUEUED", "command_id": cmd_id}

    def close_order(self, ticket: int) -> Dict[str, Any]:
        """Queues a position close command for MT5."""
        cmd_id = f"cmd_close_{ticket}_{self.cmd_counter}"
        self.cmd_counter += 1
        
        command = {
            "id": cmd_id,
            "action": "ORDER_CLOSE",
            "ticket": ticket
        }
        
        try:
            resp = httpx.post(f"{self.base_url}/api/mt5/queue_command", json=command, timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

        _pending_commands.append(command)
        return {"status": "QUEUED", "command_id": cmd_id}

    def modify_order(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> Dict[str, Any]:
        """Queues an order modification for MT5."""
        cmd_id = f"cmd_mod_{ticket}_{self.cmd_counter}"
        self.cmd_counter += 1
        
        command = {
            "id": cmd_id,
            "action": "ORDER_MODIFY",
            "ticket": ticket,
            "sl": sl,
            "tp": tp
        }
        
        try:
            resp = httpx.post(f"{self.base_url}/api/mt5/queue_command", json=command, timeout=3.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass

        _pending_commands.append(command)
        return {"status": "QUEUED", "command_id": cmd_id}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("open_positions", [])
        except Exception:
            pass
        return _mt5_state["open_positions"]

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("closed_orders", [])
        except Exception:
            pass
        return _mt5_state["closed_orders"]

    def consume_recently_closed(self) -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(f"{self.base_url}/api/mt5/recently_closed", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("recently_closed", [])
        except Exception:
            pass

        recent = list(_mt5_state["recently_closed"])
        _mt5_state["recently_closed"].clear()
        return recent
