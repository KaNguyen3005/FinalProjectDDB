from __future__ import annotations

import random
import struct
from pathlib import Path


PAGE_STRUCT = struct.Struct("<q")


def create_snapshot(path: str | Path, pages: int, *, seed: int = 42) -> None:
    """Create a deterministic binary snapshot used as the simulated database."""
    rng = random.Random(seed)
    snapshot_path = Path(path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with snapshot_path.open("wb") as fh:
        for _ in range(pages):
            fh.write(PAGE_STRUCT.pack(rng.randint(0, 1_000_000)))


def read_page(path: str | Path, page_id: int) -> int:
    """Read one simulated page by seeking to its fixed-width slot."""
    with Path(path).open("rb") as fh:
        fh.seek(page_id * PAGE_STRUCT.size)
        data = fh.read(PAGE_STRUCT.size)
    if len(data) != PAGE_STRUCT.size:
        raise IndexError(f"page {page_id} is outside snapshot")
    return PAGE_STRUCT.unpack(data)[0]


def write_page(path: str | Path, page_id: int, value: int) -> None:
    """Overwrite one page in place; recovery uses this for REDO and UNDO."""
    with Path(path).open("r+b") as fh:
        fh.seek(page_id * PAGE_STRUCT.size)
        fh.write(PAGE_STRUCT.pack(value))


def page_count(path: str | Path) -> int:
    """Return the number of fixed-width pages in a snapshot file."""
    size = Path(path).stat().st_size
    if size % PAGE_STRUCT.size != 0:
        raise ValueError(f"invalid snapshot size: {size}")
    return size // PAGE_STRUCT.size
