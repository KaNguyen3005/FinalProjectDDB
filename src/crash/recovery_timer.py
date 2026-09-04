from __future__ import annotations

"""Đồng hồ đo thời gian recovery bằng monotonic performance clock."""

import time
from dataclasses import dataclass


@dataclass
class RecoveryTimer:
    """Đo elapsed time ổn định, không phụ thuộc thay đổi system clock."""

    started_at: float | None = None
    stopped_at: float | None = None

    def start(self) -> None:
        """Bắt đầu hoặc restart timer."""
        self.started_at = time.perf_counter()
        self.stopped_at = None

    def stop(self) -> float:
        """Dừng timer và trả về số giây đã trôi qua."""
        if self.started_at is None:
            raise RuntimeError("timer has not been started")
        self.stopped_at = time.perf_counter()
        return self.elapsed

    @property
    def elapsed(self) -> float:
        """Trả elapsed hiện tại; nếu chưa stop thì vẫn tiếp tục chạy."""
        if self.started_at is None:
            return 0.0
        end = self.stopped_at if self.stopped_at is not None else time.perf_counter()
        return end - self.started_at
