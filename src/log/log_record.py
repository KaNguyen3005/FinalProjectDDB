from __future__ import annotations

import struct
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import BinaryIO, Iterable


class RecordType(IntEnum):
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
NO_PAGE = 0xFFFFFFFF
NO_IMAGE = -1
NO_LSN = 0


@dataclass(frozen=True)
class LogRecord:
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
        if not self.path.exists():
            return 1
        size = self.path.stat().st_size
        if size % LogRecord.SIZE != 0:
            raise ValueError(f"corrupt WAL size: {size}")
        return size // LogRecord.SIZE + 1


def iter_log_records(path: str | Path) -> Iterable[LogRecord]:
    file_path = Path(path)
    if not file_path.exists():
        return

    with file_path.open("rb") as fh:
        yield from iter_log_records_from_file(fh)


def iter_log_records_from_file(fh: BinaryIO) -> Iterable[LogRecord]:
    while chunk := fh.read(LogRecord.SIZE):
        if len(chunk) != LogRecord.SIZE:
            raise ValueError("truncated log record")
        yield LogRecord.unpack(chunk)
