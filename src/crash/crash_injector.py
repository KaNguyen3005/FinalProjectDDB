from __future__ import annotations

from multiprocessing import Process


class CrashInjector:
    def crash(self, process: Process) -> None:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
