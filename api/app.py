from __future__ import annotations

"""Cấu hình FastAPI app, static UI và WebSocket endpoint."""

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.routers import benchmark, demo, logs
from api.websocket.manager import manager


ROOT = Path(__file__).resolve().parents[1]


def create_app() -> FastAPI:
    """Lắp router API, trang UI tĩnh và kênh WebSocket realtime."""
    app = FastAPI(title="RTO Disaster Recovery Benchmark")
    # Mỗi router phụ trách một màn hình/chức năng chính của app.
    app.include_router(demo.router)
    app.include_router(benchmark.router)
    app.include_router(logs.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse(url="/demo")

    @app.get("/demo")
    def demo_page() -> FileResponse:
        return FileResponse(ROOT / "ui" / "demo.html")

    @app.get("/benchmark")
    def benchmark_page() -> FileResponse:
        return FileResponse(ROOT / "ui" / "benchmark.html")

    @app.get("/logs")
    def logs_page() -> FileResponse:
        return FileResponse(ROOT / "ui" / "logs.html")

    @app.websocket("/ws/events")
    async def websocket_events(websocket: WebSocket) -> None:
        """Giữ kết nối browser để các router broadcast event realtime."""
        await manager.connect(websocket)
        try:
            while True:
                # Server không cần xử lý message từ client; receive để giữ socket sống.
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(websocket)

    ui_dir = ROOT / "ui"
    if ui_dir.exists():
        app.mount("/", StaticFiles(directory=ui_dir, html=True), name="ui")

    return app


app = create_app()
