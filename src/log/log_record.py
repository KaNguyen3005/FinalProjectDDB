from __future__ import annotations

"""Mô hình WAL nhị phân dùng chung cho sinh dữ liệu, recovery và UI.

File này cố tình giữ record có kích thước cố định để LSN có thể tăng tuần tự
và việc đọc log sau crash đơn giản, dễ kiểm chứng trong demo.
"""

import struct
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import BinaryIO, Iterable


class RecordType(IntEnum):
    """Các loại record mà toàn bộ simulator hiểu và hiển thị được."""

    START = 0
    UPDATE = 1
    COMMIT = 2
    ABORT = 3
    BEGIN_CHECKPOINT = 4
    END_CHECKPOINT = 5
    PREPARE = 6
    READY = 7


MAGIC = b"RTO1"
VERSION = 1
# Các sentinel này giúp record nhị phân vẫn có đủ field cố định dù record
# không gắn với page, before/after image hoặc redo_lsn cụ thể.
NO_PAGE = 0xFFFFFFFF
NO_IMAGE = -1
NO_LSN = 0


@dataclass(frozen=True)
class LogRecord:
    """Một WAL entry có kích thước cố định.

    UPDATE record lưu cả before_image và after_image để recovery có thể REDO
    transaction đã commit hoặc UNDO transaction abort/loser từ cùng một log.
    """

    record_type: RecordType
    lsn: int
    txn_id: int = 0
    page_id: int | None = None
    before_image: int = NO_IMAGE
    after_image: int = NO_IMAGE
    redo_lsn: int = NO_LSN
    node_id: str = "A"
    timestamp: float = 0.0

    STRUCT = struct.Struct("<4sBBH Q d I I q q Q")
    SIZE = STRUCT.size

    def __post_init__(self) -> None:
        # Binary format chỉ dành đúng 1 byte cho node_id để record luôn cố định.
        if self.lsn < 0:
            raise ValueError("lsn must be non-negative")
        if len(self.node_id) != 1 or ord(self.node_id) > 255:
            raise ValueError("node_id must be a single byte character")

    @classmethod
    def create(
        cls,
        record_type: RecordType,
        lsn: int,
        *,
        txn_id: int = 0,
        page_id: int | None = None,
        before_image: int = NO_IMAGE,
        after_image: int = NO_IMAGE,
        redo_lsn: int = NO_LSN,
        node_id: str = "A",
    ) -> "LogRecord":
        return cls(
            record_type=record_type,
            lsn=lsn,
            txn_id=txn_id,
            page_id=page_id,
            before_image=before_image,
            after_image=after_image,
            redo_lsn=redo_lsn,
            node_id=node_id,
            timestamp=time.time(),
        )

    def pack(self) -> bytes:
        """Đóng gói record thành bytes để ghi xuống WAL file."""
        # None không ghi trực tiếp được vào struct, nên đổi sang sentinel.
        page_id = NO_PAGE if self.page_id is None else self.page_id
        return self.STRUCT.pack(
            MAGIC,
            VERSION,
            int(self.record_type),
            ord(self.node_id),
            self.lsn,
            self.timestamp,
            self.txn_id,
            page_id,
            self.before_image,
            self.after_image,
            self.redo_lsn,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "LogRecord":
        """Đọc một record nhị phân và kiểm tra magic/version để phát hiện sai format."""
        if len(data) != cls.SIZE:
            raise ValueError(f"expected {cls.SIZE} bytes, got {len(data)}")

        (
            magic,
            version,
            record_type,
            node_id,
            lsn,
            timestamp,
            txn_id,
            page_id,
            before_image,
            after_image,
            redo_lsn,
        ) = cls.STRUCT.unpack(data)

        if magic != MAGIC:
            raise ValueError("invalid log record magic")
        if version != VERSION:
            raise ValueError(f"unsupported log record version: {version}")

        return cls(
            record_type=RecordType(record_type),
            lsn=lsn,
            txn_id=txn_id,
            page_id=None if page_id == NO_PAGE else page_id,
            before_image=before_image,
            after_image=after_image,
            redo_lsn=redo_lsn,
            node_id=chr(node_id),
            timestamp=timestamp,
        )


class WalWriter:
    """Writer append-only; mỗi lần append tự cấp LSN tăng dần."""

    def __init__(self, path: str | Path, node_id: str = "A") -> None:
        self.path = Path(path)
        self.node_id = node_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._next_lsn = self._discover_next_lsn()

    @property
    def next_lsn(self) -> int:
        return self._next_lsn

    def append(
        self,
        record_type: RecordType,
        *,
        txn_id: int = 0,
        page_id: int | None = None,
        before_image: int = NO_IMAGE,
        after_image: int = NO_IMAGE,
        redo_lsn: int = NO_LSN,
    ) -> LogRecord:
        """Ghi một record xuống file và trả lại object để caller có thể stream ra UI."""
        record = LogRecord.create(
            record_type,
            self._next_lsn,
            txn_id=txn_id,
            page_id=page_id,
            before_image=before_image,
            after_image=after_image,
            redo_lsn=redo_lsn,
            node_id=self.node_id,
        )
        with self.path.open("ab") as fh:
            fh.write(record.pack())
        self._next_lsn += 1
        return record

    def _discover_next_lsn(self) -> int:
        """Tìm LSN tiếp theo khi mở lại WAL cũ, dùng cho live append sau Apply Config."""
        if not self.path.exists():
            return 1
        size = self.path.stat().st_size
        if size % LogRecord.SIZE != 0:
            raise ValueError(f"corrupt WAL size: {size}")
        return size // LogRecord.SIZE + 1


def iter_log_records(path: str | Path) -> Iterable[LogRecord]:
    """Duyệt tuần tự WAL file; recovery và log inspector dùng chung hàm này."""
    file_path = Path(path)
    if not file_path.exists():
        return

    with file_path.open("rb") as fh:
        yield from iter_log_records_from_file(fh)


def iter_log_records_from_file(fh: BinaryIO) -> Iterable[LogRecord]:
    """Đọc từng chunk đúng LogRecord.SIZE để phát hiện file WAL bị truncate."""
    while chunk := fh.read(LogRecord.SIZE):
        if len(chunk) != LogRecord.SIZE:
            raise ValueError("truncated log record")
        yield LogRecord.unpack(chunk)
