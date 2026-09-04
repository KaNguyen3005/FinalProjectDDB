from __future__ import annotations

"""Quản lý danh sách WebSocket client đang kết nối."""

from fastapi import WebSocket


class ConnectionManager:
    """Lưu socket đang active và broadcast JSON event tới toàn bộ UI."""

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept kết nối browser mới và đưa vào danh sách nhận event."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Gỡ socket khi browser đóng tab hoặc mất kết nối."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, event: dict) -> None:
        """Gửi event tới mọi client và loại bỏ socket đã stale."""
        stale = []
        for websocket in self.active_connections:
            try:
                await websocket.send_json(event)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


manager = ConnectionManager()
