from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RecoveryTimer:
    started_at: float | None = None
    stopped_at: float | None = None

    def start(self) -> None:
        self.started_at = time.perf_counter()
        self.stopped_at = None

    def stop(self) -> float:
        if self.started_at is None:
            raise RuntimeError("timer has not been started")
        self.stopped_at = time.perf_counter()
        return self.elapsed

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.stopped_at if self.stopped_at is not None else time.perf_counter()
        return end - self.started_at
