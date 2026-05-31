from __future__ import annotations

from multiprocessing import Process


class CrashInjector:
    """Small helper for tests or demos that need to terminate a child process."""

    def crash(self, process: Process) -> None:
        """Terminate the process and wait briefly so no child is left running."""
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
