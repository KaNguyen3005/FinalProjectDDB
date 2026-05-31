from __future__ import annotations

from fastapi import WebSocket


class ConnectionManager:
    """Track active WebSocket clients and fan out JSON events."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new browser connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection if it is currently registered."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event: dict) -> None:
        """Send one event to every client and drop stale sockets."""
        stale = []
        for websocket in self.active_connections:
            try:
                await websocket.send_json(event)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


manager = ConnectionManager()
