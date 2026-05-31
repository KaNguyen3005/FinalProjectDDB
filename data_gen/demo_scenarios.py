from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from src.checkpoint.checkpoint_manager import CheckpointManager
from src.log.log_record import RecordType, WalWriter
from src.storage import create_snapshot, read_page, write_page


Decision = Literal["COMMIT", "ABORT", "IN_DOUBT", "LOSER"]


@dataclass(frozen=True)
class DemoScenario:
    id: str
    title: str
    description: str
    checkpoint_interval_min: int
    transactions: int
    pages: int
    expected: str
    coordinator_decisions: dict[int, str] = None
    checkpoint_failure: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["coordinator_decisions"] = self.coordinator_decisions or {}
        return data


SCENARIOS: dict[str, DemoScenario] = {
    "fast_checkpoint_clean": DemoScenario(
        id="fast_checkpoint_clean",
        title="Fast checkpoint: clean recovery",
        description="Short log tail with committed transactions only; shows fast Analysis and Partial Redo.",
        checkpoint_interval_min=1,
        transactions=8,
        pages=24,
        expected="Low RTO, no Global Undo, no in-doubt transactions.",
        coordinator_decisions={},
    ),
    "long_checkpoint_heavy_redo": DemoScenario(
        id="long_checkpoint_heavy_redo",
        title="Long checkpoint: heavy redo",
        description="Longer tail after the last checkpoint; committed updates dominate recovery work.",
        checkpoint_interval_min=10,
        transactions=28,
        pages=48,
        expected="More records scanned and more Partial Redo records.",
        coordinator_decisions={},
    ),
    "global_undo_loser": DemoScenario(
        id="global_undo_loser",
        title="Loser transactions: Global Undo",
        description="Includes aborted and incomplete transactions after checkpoint.",
        checkpoint_interval_min=5,
        transactions=14,
        pages=32,
        expected="Global Undo restores before images for loser and aborted transactions.",
        coordinator_decisions={},
    ),
    "in_doubt_2pc": DemoScenario(
        id="in_doubt_2pc",
        title="2PC in-doubt transaction",
        description="Includes PREPARE and READY without a final COMMIT or ABORT.",
        checkpoint_interval_min=5,
        transactions=12,
        pages=32,
        expected="Recovery asks the coordinator: TXN#6 commits globally, TXN#8 aborts globally.",
        coordinator_decisions={6: "COMMIT", 8: "ABORT"},
    ),
    "checkpoint_failure": DemoScenario(
        id="checkpoint_failure",
        title="Checkpoint failure: BEGIN without END",
        description="Writes BEGIN_CHECKPOINT and crashes before END_CHECKPOINT is logged.",
        checkpoint_interval_min=10,
        transactions=10,
        pages=24,
        expected="Recovery ignores the incomplete checkpoint and falls back to the prior valid END_CHECKPOINT.",
        coordinator_decisions={},
        checkpoint_failure=True,
    ),
}


def list_scenarios() -> list[dict]:
    return [scenario.to_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> DemoScenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown demo scenario: {scenario_id}") from exc


def generate_demo_scenario(
    scenario_id: str,
    log_path: str | Path,
    snapshot_path: str | Path,
    *,
    seed: int = 42,
) -> DemoScenario:
    scenario = get_scenario(scenario_id)
    log_file = Path(log_path)
    snapshot_file = Path(snapshot_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.unlink(missing_ok=True)

    # Every demo scenario starts from a fresh snapshot and an initial checkpoint.
    create_snapshot(snapshot_file, scenario.pages, seed=seed)

    writer = WalWriter(log_file)
    checkpoint = CheckpointManager(writer)
    checkpoint.write_checkpoint()

    # Each branch below builds one story for the demo: clean recovery, heavy redo,
    # loser undo, in-doubt 2PC, or checkpoint failure.
    if scenario_id == "fast_checkpoint_clean":
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(5, 9)])
    elif scenario_id == "long_checkpoint_heavy_redo":
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 4)])
        checkpoint.write_checkpoint()
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 3) for txn in range(4, 29)])
    elif scenario_id == "global_undo_loser":
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(
            writer,
            snapshot_file,
            [
                (5, "COMMIT", 2),
                (6, "ABORT", 2),
                (7, "LOSER", 2),
                (8, "COMMIT", 1),
                (9, "LOSER", 3),
                (10, "ABORT", 1),
                (11, "COMMIT", 2),
                (12, "LOSER", 1),
                (13, "COMMIT", 1),
                (14, "COMMIT", 1),
            ],
        )
    elif scenario_id == "in_doubt_2pc":
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(
            writer,
            snapshot_file,
            [
                (5, "COMMIT", 2),
                (6, "IN_DOUBT", 2),
                (7, "COMMIT", 1),
                (8, "IN_DOUBT", 1),
                (9, "ABORT", 1),
                (10, "COMMIT", 2),
                (11, "LOSER", 1),
                (12, "COMMIT", 1),
            ],
        )
    elif scenario_id == "checkpoint_failure":
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(5, 8)])
        checkpoint.write_checkpoint(fail_after_begin=True)
        _write_plan(writer, snapshot_file, [(txn, "LOSER", 1) for txn in range(8, 11)])
    else:
        raise ValueError(f"unknown demo scenario: {scenario_id}")

    return scenario


def _write_plan(
    writer: WalWriter,
    snapshot_path: Path,
    plan: list[tuple[int, Decision, int]],
) -> None:
    page_count = max(1, snapshot_path.stat().st_size // 8)
    for txn_id, decision, updates in plan:
        # Build a deterministic pattern so the same scenario always reproduces the same WAL.
        writer.append(RecordType.START, txn_id=txn_id)
        for index in range(updates):
            page_id = (txn_id * 7 + index * 5) % page_count
            before = read_page(snapshot_path, page_id)
            after = before + txn_id * 100 + index + 1
            writer.append(
                RecordType.UPDATE,
                txn_id=txn_id,
                page_id=page_id,
                before_image=before,
                after_image=after,
            )
            write_page(snapshot_path, page_id, after)

        if decision == "COMMIT":
            writer.append(RecordType.COMMIT, txn_id=txn_id)
        elif decision == "ABORT":
            writer.append(RecordType.ABORT, txn_id=txn_id)
        elif decision == "IN_DOUBT":
            # In-doubt transactions stop after PREPARE/READY so recovery must ask the coordinator.
            writer.append(RecordType.PREPARE, txn_id=txn_id)
            writer.append(RecordType.READY, txn_id=txn_id)
        elif decision == "LOSER":
            # Loser transactions are left incomplete on purpose so Global Undo has work to do.
            continue
        else:
            raise ValueError(f"unsupported decision: {decision}")
