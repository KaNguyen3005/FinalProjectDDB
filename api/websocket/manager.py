from __future__ import annotations

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event: dict) -> None:
        stale = []
        for websocket in self.active_connections:
            try:
                await websocket.send_json(event)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


manager = ConnectionManager()
