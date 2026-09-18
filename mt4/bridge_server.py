"""
FastAPI Server and Client Bridge for MetaTrader 4.
Enables bidirectional communication between Python and MT4 via AgenticMT4Bridge.mq4.
"""

from typing import Dict, Any, List, Optional
import time
import httpx
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


@app.post("/api/mt4/queue_command")
async def queue_command_endpoint(command: Dict[str, Any]):
    """Receives commands from external client processes."""
    _pending_commands.append(command)
    logger.info(
        f"[MT4-QUEUE] Queued via REST: {command.get('action')} "
        f"{command.get('volume')} lots on {command.get('symbol')}"
    )
    return {"status": "QUEUED", "command_id": command.get("id")}


@app.post("/api/mt4/confirm")
async def confirm_execution(payload: ConfirmPayload):
    """Called by MT4 EA to confirm command outcome."""
    _execution_results[payload.command_id] = payload.model_dump()
    logger.info(f"[MT4-CONFIRM] Command {payload.command_id}: status={payload.status}, ticket=#{payload.ticket}")
    return {"status": "RECORDED"}


@app.get("/api/mt4/execution_results")
async def get_execution_result(command_id: str):
    """Returns the EA's confirmation for a command, or null if not yet confirmed."""
    return {"command_id": command_id, "result": _execution_results.get(command_id)}


@app.post("/api/mt4/bars")
async def receive_bars(payload: BarsPayload):
    """Called by MT4 to upload historical or incoming bars."""
    global _cached_bars
    _cached_bars = payload.bars
    return {"status": "BARS_STORED", "count": len(payload.bars)}


@app.get("/api/mt4/account")
async def get_account_state():
    """Returns live account state for client brokers."""
    return {
        "account_number": _telemetry_state["account_number"],
        "balance": _telemetry_state["balance"],
        "equity": _telemetry_state["equity"],
        "bid": _telemetry_state["bid"],
        "ask": _telemetry_state["ask"],
        "symbol": _telemetry_state["symbol"],
        "last_sync": _telemetry_state["last_sync"],
        "open_positions": _telemetry_state["open_positions"],
        "closed_orders": _telemetry_state["closed_orders"]
    }


class MT4BridgeBroker(BaseBroker):
    """
    Python broker adapter communicating with the live MT4 Bridge.

    Delivery goes over REST (with an in-process fallback only when the bridge
    lives in the same process, e.g. under TestClient), mirroring
    MT5BridgeBroker so both adapters behave identically.
    """

    def __init__(self, host: str = None, port: int = None, in_process: bool = False):
        """
        `in_process=True` makes the broker append straight to this module's
        _pending_commands / _execution_results dicts. Only valid when the bridge
        app runs in the SAME process (e.g. FastAPI TestClient). Production runs
        bridge and agent in separate containers, where that dict is unreachable —
        hence REST by default.
        """
        self.host = host or config.mt4_host
        self.port = port or config.mt4_port
        self.base_url = f"http://{self.host}:{self.port}"
        self.in_process = in_process
        self.cmd_counter = 1

    def _queue_command(self, command: Dict[str, Any], timeout: float = 5.0) -> Dict[str, Any]:
        """
        Delivers a command to the bridge. Raises RuntimeError when the bridge
        cannot be reached, so a failure never masquerades as success.
        """
        if self.in_process:
            _pending_commands.append(command)
            logger.info(
                f"[MT4-QUEUE] Queued in-process: {command.get('action')} "
                f"{command.get('volume')} lots on {command.get('symbol')}"
            )
            return {"status": "QUEUED", "command_id": command.get("id")}

        try:
            resp = httpx.post(
                f"{self.base_url}/api/mt4/queue_command", json=command, timeout=timeout
            )
        except Exception as e:
            raise RuntimeError(
                f"[MT4-QUEUE] Cannot reach MT4 bridge at {self.base_url} "
                f"({type(e).__name__}: {e}). Command {command.get('id')} was NOT queued."
            ) from e

        if resp.status_code != 200:
            raise RuntimeError(
                f"[MT4-QUEUE] Bridge rejected command {command.get('id')}: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        return resp.json()

    def _await_confirmation(
        self,
        cmd_id: str,
        timeout: float = 10.0,
        poll_interval: float = 0.25
    ) -> Optional[Dict[str, Any]]:
        """Polls the bridge until the MT4 EA confirms execution of `cmd_id`."""
        if self.in_process:
            return _execution_results.get(cmd_id)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = httpx.get(
                    f"{self.base_url}/api/mt4/execution_results",
                    params={"command_id": cmd_id},
                    timeout=5.0
                )
                if resp.status_code == 200:
                    result = resp.json().get("result")
                    if result:
                        return result
            except Exception as e:
                logger.warning(f"[MT4-CONFIRM] Poll failed for {cmd_id}: {type(e).__name__}: {e}")
            time.sleep(poll_interval)
        return None

    def get_account_info(self) -> Dict[str, Any]:
        """Returns account telemetry reported by MT4."""
        if not self.in_process:
            try:
                resp = httpx.get(f"{self.base_url}/api/mt4/account", timeout=3.0)
                if resp.status_code == 200:
                    data = resp.json()
                    data["open_positions_count"] = len(data.get("open_positions", []))
                    return data
            except Exception as e:
                logger.warning(
                    f"[MT4-ACCOUNT] Bridge unreachable ({type(e).__name__}: {e}); "
                    f"using in-process state."
                )

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
        comment: str = "",
        await_confirm: bool = True,
        confirm_timeout: float = 10.0
    ) -> Dict[str, Any]:
        """Queues an open command for the MT4 EA and waits for confirmation."""
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
        response = self._queue_command(command)
        logger.info(f"[MT4-QUEUE] Delivered to bridge: {order_type} {lots} lots on {symbol} cmd={cmd_id}")

        if not await_confirm:
            return response

        confirmation = self._await_confirmation(cmd_id, timeout=confirm_timeout)
        if confirmation is None:
            logger.warning(
                f"[MT4-CONFIRM] No EA confirmation for {cmd_id} within {confirm_timeout}s. "
                f"Command is queued but unconfirmed."
            )
            return {**response, "confirmed": False}

        status = confirmation.get("status")
        if status not in ("SUCCESS", "EXECUTED", "FILLED"):
            raise RuntimeError(
                f"[MT4-EXEC] EA rejected {cmd_id}: status={status}, "
                f"message={confirmation.get('message')}"
            )
        return {**response, "confirmed": True, "ticket": confirmation.get("ticket"), **confirmation}

    def close_order(
        self,
        ticket: int,
        await_confirm: bool = True,
        confirm_timeout: float = 10.0
    ) -> Dict[str, Any]:
        """Queues a close command for MT4 EA."""
        cmd_id = f"cmd_close_{ticket}_{self.cmd_counter}"
        self.cmd_counter += 1

        command = {
            "id": cmd_id,
            "action": "ORDER_CLOSE",
            "ticket": ticket
        }
        response = self._queue_command(command)

        if not await_confirm:
            return response

        confirmation = self._await_confirmation(cmd_id, timeout=confirm_timeout)
        if confirmation is None:
            logger.warning(f"[MT4-CONFIRM] No EA confirmation for close {cmd_id} within {confirm_timeout}s.")
            return {**response, "confirmed": False}
        return {**response, "confirmed": True, **confirmation}

    def modify_order(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        await_confirm: bool = True,
        confirm_timeout: float = 10.0
    ) -> Dict[str, Any]:
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
        response = self._queue_command(command)

        if not await_confirm:
            return response

        confirmation = self._await_confirmation(cmd_id, timeout=confirm_timeout)
        if confirmation is None:
            logger.warning(f"[MT4-CONFIRM] No EA confirmation for modify {cmd_id} within {confirm_timeout}s.")
            return {**response, "confirmed": False}
        return {**response, "confirmed": True, **confirmation}

    def get_open_positions(self) -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(f"{self.base_url}/api/mt4/account", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("open_positions", [])
        except Exception as e:
            logger.warning(f"[MT4-POSITIONS] Bridge unreachable ({type(e).__name__}: {e}).")
        return _telemetry_state["open_positions"]

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(f"{self.base_url}/api/mt4/account", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("closed_orders", [])
        except Exception as e:
            logger.warning(f"[MT4-HISTORY] Bridge unreachable ({type(e).__name__}: {e}).")
        return _telemetry_state["closed_orders"]
