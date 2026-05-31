from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class RecoveryTimer:
    """Measure elapsed recovery time with a monotonic performance clock."""

    started_at: float | None = None
    stopped_at: float | None = None

    def start(self) -> None:
        """Start or restart the timer."""
        self.started_at = time.perf_counter()
        self.stopped_at = None

    def stop(self) -> float:
        """Stop the timer and return the elapsed seconds."""
        if self.started_at is None:
            raise RuntimeError("timer has not been started")
        self.stopped_at = time.perf_counter()
        return self.elapsed

    @property
    def elapsed(self) -> float:
        """Return elapsed seconds; keep ticking until stop() is called."""
        if self.started_at is None:
            return 0.0
        end = self.stopped_at if self.stopped_at is not None else time.perf_counter()
        return end - self.started_at
