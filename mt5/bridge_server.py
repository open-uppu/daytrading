"""
FastAPI Server and Client Bridge for MetaTrader 5 (MT5).
Enables bidirectional communication between Python and MT5 via AgenticMT5Bridge.mq5.
"""

from typing import Dict, Any, List, Optional
import time
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pandas as pd
import logging
from config import config
from mt5.broker_interface import BaseBroker

logger = logging.getLogger("mt5_bridge_server")

app = FastAPI(title="MT5 Agentic Bridge API", version="2.0.0")


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
        if self.in_process:
            return _execution_results.get(cmd_id)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
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
        comment: str = "",
        await_confirm: bool = True,
        confirm_timeout: float = 10.0
    ) -> Dict[str, Any]:
        """
        Queues an MQL5 trade order for the MT5 EA to execute.

        Raises RuntimeError if the command could not be delivered to the bridge.
        When await_confirm is True, blocks until the EA reports back (or timeout)
        so callers get a real fill status instead of a bare "QUEUED".
        """
        cmd_id = self._next_cmd_id("mt5")

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
        confirm_timeout: float = 10.0
    ) -> Dict[str, Any]:
        """Queues a position close command for MT5 and waits for EA confirmation."""
        cmd_id = self._next_cmd_id("close")

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
        confirm_timeout: float = 10.0
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
        try:
            resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("open_positions", [])
        except Exception as e:
            logger.warning(f"[MT5-POSITIONS] Bridge unreachable ({type(e).__name__}: {e}); using in-process state.")
        return _mt5_state["open_positions"]

    def get_closed_orders(self) -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(f"{self.base_url}/api/mt5/account", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("closed_orders", [])
        except Exception as e:
            logger.warning(f"[MT5-HISTORY] Bridge unreachable ({type(e).__name__}: {e}); using in-process state.")
        return _mt5_state["closed_orders"]

    def consume_recently_closed(self) -> List[Dict[str, Any]]:
        try:
            resp = httpx.get(f"{self.base_url}/api/mt5/recently_closed", timeout=3.0)
            if resp.status_code == 200:
                return resp.json().get("recently_closed", [])
        except Exception as e:
            logger.warning(f"[MT5-RECENT] Bridge unreachable ({type(e).__name__}: {e}); using in-process state.")

        recent = list(_mt5_state["recently_closed"])
        _mt5_state["recently_closed"].clear()
        return recent
