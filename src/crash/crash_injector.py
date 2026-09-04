from __future__ import annotations

"""Helper giả lập crash bằng cách terminate process con."""

from multiprocessing import Process


class CrashInjector:
    """Dùng cho test/demo cần dừng đột ngột một process node."""

    def crash(self, process: Process) -> None:
        """Terminate process và join ngắn để không để lại process con chạy nền."""
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
