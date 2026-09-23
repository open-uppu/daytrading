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
        for connection in list(self.active_connections):
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
                    **bars_payload,
                })
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_hub.disconnect(websocket)
    except Exception as exc:
        logger.error(f"[WebSocketLive] Error: {exc}")
        ws_hub.disconnect(websocket)


def mount_frontend(
    app: FastAPI,
    mt5_state_ref: Optional[Dict[str, Any]] = None,
    cached_bars_ref: Optional[Dict[str, Any]] = None,
):
    """Mounts frontend routes and static directory."""
    if mt5_state_ref is not None or cached_bars_ref is not None:
        set_feed_provider(
            DashboardFeedProvider(
                mt5_state_ref=mt5_state_ref,
                cached_bars_ref=cached_bars_ref,
            )
        )
    else:
        set_feed_provider(DashboardFeedProvider())

    app.include_router(frontend_router)

    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)

    if not any(getattr(route, "path", None) == "/" for route in app.routes):
        @app.get("/", include_in_schema=False)
        async def serve_index():
            index_file = static_dir / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
            return {"status": "Frontend initialized. Static index.html loading..."}

    if not any(getattr(route, "path", None) == "/static" for route in app.routes):
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
