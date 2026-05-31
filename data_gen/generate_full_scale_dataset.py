from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.log.log_record import LogRecord, RecordType


DEFAULT_SNAPSHOT_BYTES = 500 * 1024 * 1024
DEFAULT_LOG_BYTES = 1024 * 1024 * 1024


def align_up(value: int, multiple: int) -> int:
    """Round a byte size up to the next multiple."""
    if multiple <= 0:
        raise ValueError("multiple must be positive")
    remainder = value % multiple
    return value if remainder == 0 else value + (multiple - remainder)


def create_large_snapshot(path: str | Path, size_bytes: int = DEFAULT_SNAPSHOT_BYTES) -> None:
    """Create a sparse-like snapshot file with the requested byte size."""
    snapshot_path = Path(path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    # A truncated file is enough here because the storage layer treats the snapshot as raw pages.
    with snapshot_path.open("wb") as fh:
        fh.truncate(size_bytes)


def build_log_pattern() -> bytes:
    """Build a repeatable WAL pattern containing commit, abort, and 2PC cases."""
    records: list[bytes] = []
    lsn = 1

    # Seed the large log with a valid checkpoint pair so recovery always has a safe base point.
    records.append(LogRecord.create(RecordType.BEGIN_CHECKPOINT, lsn).pack())
    lsn += 1
    records.append(LogRecord.create(RecordType.END_CHECKPOINT, lsn, redo_lsn=1).pack())
    lsn += 1

    # Repeat a compact transaction pattern that includes commits, aborts, and 2PC records.
    for txn_id in range(1, 257):
        page_id = txn_id % 1024
        before = txn_id * 10
        after = before + 1
        records.append(LogRecord.create(RecordType.START, lsn, txn_id=txn_id).pack())
        lsn += 1
        records.append(
            LogRecord.create(
                RecordType.UPDATE,
                lsn,
                txn_id=txn_id,
                page_id=page_id,
                before_image=before,
                after_image=after,
            ).pack()
        )
        lsn += 1
        if txn_id % 16 == 0:
            records.append(LogRecord.create(RecordType.PREPARE, lsn, txn_id=txn_id).pack())
            lsn += 1
            records.append(LogRecord.create(RecordType.READY, lsn, txn_id=txn_id).pack())
            lsn += 1
        elif txn_id % 11 == 0:
            records.append(LogRecord.create(RecordType.ABORT, lsn, txn_id=txn_id).pack())
            lsn += 1
        else:
            records.append(LogRecord.create(RecordType.COMMIT, lsn, txn_id=txn_id).pack())
            lsn += 1

    return b"".join(records)


def create_large_wal(path: str | Path, size_bytes: int = DEFAULT_LOG_BYTES) -> None:
    """Write a large WAL by repeating the valid record pattern."""
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pattern = build_log_pattern()
    if not pattern:
        raise ValueError("log pattern is empty")

    # Keep the WAL byte-aligned so iter_log_records() can read it back safely.
    size_bytes = align_up(size_bytes, LogRecord.SIZE)
    repeats = size_bytes // len(pattern)
    remainder = size_bytes % len(pattern)

    with log_path.open("wb") as fh:
        for _ in range(repeats):
            fh.write(pattern)
        if remainder:
            # Write a partial tail only after the aligned repeats are in place.
            fh.write(pattern[:remainder])


def main() -> None:
    """CLI entry point for generating the full-scale benchmark dataset."""
    parser = argparse.ArgumentParser(description="Generate a full-scale 1GB WAL and 500MB snapshot dataset.")
    parser.add_argument("--log-bytes", type=int, default=DEFAULT_LOG_BYTES)
    parser.add_argument("--snapshot-bytes", type=int, default=DEFAULT_SNAPSHOT_BYTES)
    parser.add_argument("--output-dir", type=Path, default=Path("data/full_scale"))
    args = parser.parse_args()

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "transaction_log.bin"
    snapshot_path = output_dir / "db_snapshot.bin"

    create_large_snapshot(snapshot_path, args.snapshot_bytes)
    create_large_wal(log_path, args.log_bytes)

    print(f"generated snapshot: {snapshot_path} ({snapshot_path.stat().st_size} bytes)")
    print(f"generated WAL: {log_path} ({log_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
