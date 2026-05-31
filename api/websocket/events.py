from __future__ import annotations

from typing import Any


def node_status(node: str, status: str, *, txn: int = 0, lsn: int = 0) -> dict[str, Any]:
    return {"type": "node_status", "node": node, "status": status, "txn": txn, "lsn": lsn}


def crash_event(node: str, timestamp: float, *, run_elapsed_seconds: float = 0.0) -> dict[str, Any]:
    return {
        "type": "crash",
        "node": node,
        "timestamp": timestamp,
        "run_elapsed_seconds": run_elapsed_seconds,
    }


def checkpoint_failure(begin_lsn: int, redo_lsn: int, message: str) -> dict[str, Any]:
    return {
        "type": "checkpoint_failure",
        "begin_lsn": begin_lsn,
        "redo_lsn": redo_lsn,
        "message": message,
    }


def log_entry(**kwargs: Any) -> dict[str, Any]:
    return {"type": "log_entry", **kwargs}


def demo_log_stream_state(running: bool, *, generation: int = 0) -> dict[str, Any]:
    return {"type": "demo_log_stream_state", "running": running, "generation": generation}


def benchmark_progress(
    interval: int,
    run: int,
    rto: float,
    total_runs: int,
    *,
    completed_runs: int = 0,
) -> dict[str, Any]:
    return {
        "type": "benchmark_progress",
        "interval": interval,
        "run": run,
        "rto": rto,
        "total_runs": total_runs,
        "completed_runs": completed_runs,
    }
