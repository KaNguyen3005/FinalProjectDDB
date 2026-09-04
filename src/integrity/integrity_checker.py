from __future__ import annotations

"""Tiện ích kiểm tra toàn vẹn file snapshot/log bằng SHA-256."""

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    """Hash theo từng chunk để không cần nạp snapshot lớn vào RAM."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: str | Path, expected: str) -> bool:
    """So sánh digest thực tế với digest kỳ vọng."""
    return sha256_file(path) == expected

