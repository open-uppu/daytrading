"""
FastAPI Server and Client Bridge for MetaTrader 4.
Enables bidirectional communication between Python and MT4 via AgenticMT4Bridge.mq4.
"""

from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import pandas as pd
import asyncio
import logging
from config import config
from mt4.broker_interface import BaseBroker

logger = logging.getLogger("mt4_bridge_server")

app = FastAPI(title="MT4 Agentic Bridge API", version="1.0.0")

# In-Memory Bridge State
_telemetry_state = {
    "account_number": 0,
    "balance": 10000.0,
    "equity": 10000.0,
    "symbol": "XAUUSD",
    "bid": 2650.0,
    "ask": 2650.25,
    "open_positions": [],
    "closed_orders": [],
    "last_sync": ""
}
_pending_commands: List[Dict[str, Any]] = []
_execution_results: Dict[str, Any] = {}
_cached_bars: List[Dict[str, Any]] = []


class TelemetryPayload(BaseModel):
    account_number: int
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
    message: Optional[str] = ""


class BarsPayload(BaseModel):
    symbol: str
    timeframe: str
    bars: List[Dict[str, Any]]


@app.post("/api/mt4/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    """Called by MT4 EA to report live account and price telemetry."""
    global _telemetry_state
    _telemetry_state["account_number"] = payload.account_number
    _telemetry_state["balance"] = payload.balance
    _telemetry_state["equity"] = payload.equity
    _telemetry_state["symbol"] = payload.symbol
    _telemetry_state["bid"] = payload.bid
    _telemetry_state["ask"] = payload.ask
    _telemetry_state["open_positions"] = payload.open_positions
    _telemetry_state["closed_orders"] = payload.closed_orders
    _telemetry_state["last_sync"] = pd.Timestamp.now().isoformat()
    return {"status": "ACK"}


@app.get("/api/mt4/commands")
async def poll_commands():
    """Polled by MT4 EA to retrieve queued trade commands."""
    global _pending_commands
    commands = list(_pending_commands)
    _pending_commands.clear()
    return {"commands": commands}


@app.post("/api/mt4/confirm")
async def confirm_execution(payload: ConfirmPayload):
    """Called by MT4 EA to confirm command outcome."""
    _execution_results[payload.command_id] = payload.model_dump()
    return {"status": "RECORDED"}


@app.post("/api/mt4/bars")
async def receive_bars(payload: BarsPayload):
    """Called by MT4 to upload historical or incoming bars."""
    global _cached_bars
    _cached_bars = payload.bars
    return {"status": "BARS_STORED", "count": len(payload.bars)}


class MT4BridgeBroker(BaseBroker):
    """Python broker adapter communicating with the live MT4 Bridge."""

    def __init__(self, host: str = None, port: int = None):
        self.host = host or config.mt4_host
        self.port = port or config.mt4_port
        self.cmd_counter = 1

    def get_account_info(self) -> Dict[str, Any]:
        """Returns account telemetry reported by MT4."""
        return {
            "balance": _telemetry_state["balance"],
            "equity": _telemetry_state["equity"],
            "bid": _telemetry_state["bid"],
            "ask": _telemetry_state["ask"],
            "symbol": _telemetry_state["symbol"],
            "open_positions_count": len(_telemetry_state["open_positions"])
        }

    def get_market_data(self, symbol: str = "XAUUSD", timeframe: str = "M15", bars: int = 100) -> pd.DataFrame:
        """Returns cached bars or transforms telemetry into DataFrame."""
        if _cached_bars:
            df = pd.DataFrame(_cached_bars)
            return df.tail(bars).copy().reset_index(drop=True)
        # Fallback to empty with proper columns if not yet synced
        return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def open_order(
        self,
        symbol: str,
        order_type: str,
        lots: float,
        sl: float,
        tp: float,
        comment: str = ""
    ) -> Dict[str, Any]:
        """Queues an open command for MT4 EA to execute."""
        cmd_id = f"cmd_{self.cmd_counter}_{int(pd.Timestamp.now().timestamp())}"
        self.cmd_counter += 1
        
        command = {
            "id": cmd_id,
            "action": "ORDER_OPEN",
            "symbol": symbol,
            "type": order_type,
            "volume": lots,
            "sl": sl,
            "tp": tp,
            "comment": comment
        }
        _pending_commands.append(command)
        logger.info(f"[MT4-QUEUE] Queued {order_type} {lots} lots on {symbol}")
        return {"status": "QUEUED", "command_id": cmd_id}

    def close_order(self, ticket: int) -> Dict[str, Any]:
        """Queues a close command for MT4 EA."""
        cmd_id = f"cmd_close_{ticket}_{self.cmd_counter}"
        self.cmd_counter += 1
        
        command = {
            "id": cmd_id,
            "action": "ORDER_CLOSE",
            "ticket": ticket
        }
        _pending_commands.append(command)
        return {"status": "QUEUED", "command_id": cmd_id}

    def modify_order(self, ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> Dict[str, Any]:
        """Queues a modify command for MT4 EA."""
        cmd_id = f"cmd_mod_{ticket}_{self.cmd_counter}"
        self.cmd_counter += 1
        
        command = {
            "id": cmd_id,
            "action": "ORDER_MODIFY",
            "ticket": ticket,
            "sl": sl,
            "tp": tp
        }
        _pending_commands.append(command)
        return {"status": "QUEUED", "command_id": cmd_id}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        return _telemetry_state["open_positions"]

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        return _telemetry_state["closed_orders"]
