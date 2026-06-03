from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class DemoState:
    """Mutable runtime state shared by demo endpoints.

    The app is a single-process simulator, so an in-memory object is enough to
    coordinate scenario selection, node status, generated data paths, and the
    background log-stream task.
    """

    scenario_id: str = "fast_checkpoint_clean"
    checkpoint_interval_min: int = 5
    scenario_title: str = "Fast checkpoint: clean recovery"
    scenario_description: str = ""
    scenario_expected: str = ""
    coordinator_decisions: dict[int, str] = field(default_factory=dict)
    checkpoint_failure_detected: bool = False
    checkpoint_failure_message: str = ""
    recovery_interrupted: bool = False
    recovery_interrupted_message: str = ""
    crashed_node: str = "A"
    node_statuses: dict[str, str] = field(
        default_factory=lambda: {"A": "RUNNING", "B": "RUNNING", "C": "RUNNING", "COORDINATOR": "RUNNING"}
    )
    current_txn: int = 0
    current_lsn: int = 0
    stream_txn: int = 0
    stream_lsn: int = 0
    run_started_at: float = field(default_factory=time.time)
    run_id: str = "default"
    crashed_at: float | None = None
    log_stream_task: asyncio.Task | None = None
    log_stream_generation: int = 0
    live_events: list[dict] = field(default_factory=list)
    log_path: Path = ROOT / "data" / "api_demo" / "transaction_log.bin"
    snapshot_path: Path = ROOT / "data" / "api_demo" / "db_snapshot.bin"


@dataclass
class BenchmarkState:
    """Mutable runtime state for the background benchmark job."""

    running: bool = False
    started_at: float | None = None
    completed_at: float | None = None
    last_error: str | None = None
    task: asyncio.Task | None = None


demo_state = DemoState()
benchmark_state = BenchmarkState()
