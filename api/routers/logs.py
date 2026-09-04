from __future__ import annotations

"""API phục vụ màn hình WAL Log Inspector."""

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.state import demo_state
from src.log.log_record import LogRecord, iter_log_records


router = APIRouter(prefix="/api/logs", tags=["logs"])


def serialize_record(record: LogRecord) -> dict:
    """Đổi LogRecord nhị phân sang JSON để browser hiển thị được."""
    return {
        "lsn": record.lsn,
        "txn_id": record.txn_id,
        "node": record.node_id,
        "record_type": record.record_type.name,
        "page_id": record.page_id,
        "before_image": record.before_image,
        "after_image": record.after_image,
        "redo_lsn": record.redo_lsn,
        "timestamp": record.timestamp,
    }


@router.get("/records")
def records(node: str | None = None, offset: int = 0, limit: int = 100) -> dict:
    """Trả về một trang record WAL hiện tại, có thể lọc theo node."""
    path = demo_state.log_path
    all_records = list(iter_log_records(path)) if path.exists() else []
    if node:
        all_records = [record for record in all_records if record.node_id == node]
    sliced = all_records[offset : offset + limit]
    return {
        "offset": offset,
        "limit": limit,
        "total": len(all_records),
        "records": [serialize_record(record) for record in sliced],
    }


@router.get("/stream")
async def stream() -> StreamingResponse:
    """Stream WAL record mới bằng SSE cho trang logs nếu cần theo dõi realtime."""
    async def event_source():
        # seen lưu số record đã gửi để mỗi vòng chỉ emit phần mới append.
        path = Path(demo_state.log_path)
        seen = 0
        while True:
            current = list(iter_log_records(path)) if path.exists() else []
            for record in current[seen:]:
                yield f"data: {json.dumps(serialize_record(record))}\n\n"
            seen = len(current)
            await asyncio.sleep(1)

    return StreamingResponse(event_source(), media_type="text/event-stream")
