from __future__ import annotations

import asyncio
import time
from typing import Literal, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.state import demo_state
from api.websocket.events import crash_event, demo_log_stream_state, log_entry, node_status
from api.websocket.manager import manager
from data_gen.demo_scenarios import generate_demo_scenario, list_scenarios
from data_gen.generate_logs import generate_logs
from src.coordinator import CoordinatorSimulator
from src.log.log_record import iter_log_records
from src.recovery.recovery_manager import RecoveryManager


router = APIRouter(prefix="/api/demo", tags=["demo"])


class DemoConfig(BaseModel):
    checkpoint_interval_min: int = Field(default=5, ge=1)
    transactions: int = Field(default=200, ge=1)
    pages: int = Field(default=100, ge=1)
    seed: int = 42


class DemoScenarioRequest(BaseModel):
    scenario_id: str
    seed: int = 42


class RecoveryInterruptRequest(BaseModel):
    interrupt_after_events: int = Field(default=4, ge=1)


class CrashRequest(BaseModel):
    target_node: Literal["A", "B", "C"] = "A"


@router.get("/status")
def status() -> dict:
    return {
        "scenario_id": demo_state.scenario_id,
        "scenario_title": demo_state.scenario_title,
        "scenario_description": demo_state.scenario_description,
        "scenario_expected": demo_state.scenario_expected,
        "coordinator_decisions": demo_state.coordinator_decisions,
        "checkpoint_interval_min": demo_state.checkpoint_interval_min,
        "nodes": demo_state.node_statuses,
        "crashed_node": demo_state.crashed_node,
        "current_txn": demo_state.current_txn,
        "current_lsn": demo_state.current_lsn,
        "run_started_at": demo_state.run_started_at,
        "crashed_at": demo_state.crashed_at,
        "log_stream_running": demo_state.log_stream_task is not None and not demo_state.log_stream_task.done(),
        "checkpoint_failure_detected": demo_state.checkpoint_failure_detected,
        "checkpoint_failure_message": demo_state.checkpoint_failure_message,
        "recovery_interrupted": demo_state.recovery_interrupted,
        "recovery_interrupted_message": demo_state.recovery_interrupted_message,
        "run_elapsed_seconds": (
            (demo_state.crashed_at or time.time()) - demo_state.run_started_at
        ),
    }


@router.get("/scenarios")
def scenarios() -> dict:
    return {"scenarios": list_scenarios()}


@router.post("/scenario")
async def load_scenario(request: DemoScenarioRequest) -> dict:
    try:
        scenario = generate_demo_scenario(
            request.scenario_id,
            demo_state.log_path,
            demo_state.snapshot_path,
            seed=request.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _reset_demo_state(
        scenario_id=scenario.id,
        title=scenario.title,
        description=scenario.description,
        expected=scenario.expected,
        checkpoint_interval_min=scenario.checkpoint_interval_min,
        coordinator_decisions={int(txn_id): decision for txn_id, decision in (scenario.coordinator_decisions or {}).items()},
    )
    demo_state.checkpoint_failure_detected = False
    demo_state.checkpoint_failure_message = ""
    demo_state.recovery_interrupted = False
    demo_state.recovery_interrupted_message = ""
    demo_state.crashed_node = "A"
    _refresh_current_position()
    await _restart_log_stream()
    await manager.broadcast(node_status("A", "RUNNING", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
    await manager.broadcast(node_status("COORDINATOR", "RUNNING"))
    return status()


@router.post("/config")
async def configure(config: DemoConfig) -> dict:
    _reset_demo_state(
        scenario_id="custom",
        title="Custom configuration",
        description="Generated from the checkpoint interval and workload settings.",
        expected="Use this for ad-hoc recovery timing outside the curated scenarios.",
        checkpoint_interval_min=config.checkpoint_interval_min,
        coordinator_decisions={},
    )
    demo_state.checkpoint_failure_detected = False
    demo_state.checkpoint_failure_message = ""
    demo_state.recovery_interrupted = False
    demo_state.recovery_interrupted_message = ""
    demo_state.crashed_node = "A"
    generate_logs(
        demo_state.log_path,
        demo_state.snapshot_path,
        transactions=config.transactions,
        checkpoint_every=max(1, config.checkpoint_interval_min * 10),
        seed=config.seed,
        pages=config.pages,
    )
    _refresh_current_position()
    await _restart_log_stream()
    await manager.broadcast(node_status("A", "RUNNING", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
    await manager.broadcast(node_status("COORDINATOR", "RUNNING"))
    return status()


@router.post("/crash")
async def crash(request: CrashRequest | None = None) -> dict:
    if not demo_state.log_path.exists() or not demo_state.snapshot_path.exists():
        await configure(DemoConfig(checkpoint_interval_min=demo_state.checkpoint_interval_min))

    target_node = request.target_node if request else "A"
    demo_state.crashed_node = target_node
    await _stop_log_stream()
    demo_state.node_statuses[target_node] = "CRASHED"
    demo_state.crashed_at = time.time()
    run_elapsed_seconds = demo_state.crashed_at - demo_state.run_started_at
    await manager.broadcast(
        crash_event(target_node, demo_state.crashed_at, run_elapsed_seconds=run_elapsed_seconds)
    )
    await manager.broadcast(node_status(target_node, "CRASHED", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
    return status()


@router.post("/recover")
async def recover() -> dict:
    return await _run_recovery()


@router.post("/recover-interrupted")
async def recover_interrupted(request: RecoveryInterruptRequest | None = None) -> dict:
    interrupt_after_events = (request.interrupt_after_events if request else 4)
    return await _run_recovery(interrupt_after_events=interrupt_after_events)


async def _run_recovery(*, interrupt_after_events: int | None = None) -> dict:
    if not demo_state.log_path.exists() or not demo_state.snapshot_path.exists():
        await configure(DemoConfig(checkpoint_interval_min=demo_state.checkpoint_interval_min))

    target_node = demo_state.crashed_node or "A"
    await _stop_log_stream()
    demo_state.node_statuses[target_node] = "RECOVERING"
    await manager.broadcast(node_status(target_node, "RECOVERING", txn=demo_state.current_txn, lsn=demo_state.current_lsn))

    async def broadcast_event(event: dict) -> None:
        await manager.broadcast(event)

    events = []
    recovery_event_count = 0

    class RecoveryInterrupted(RuntimeError):
        pass

    def collect(event: dict) -> None:
        nonlocal recovery_event_count
        events.append(event)
        if event.get("type") in {
            "recovery_pass",
            "recovery_record",
            "in_doubt_txn",
            "coordinator_query",
            "coordinator_decision",
            "checkpoint_failure",
        }:
            recovery_event_count += 1
            if interrupt_after_events is not None and recovery_event_count >= interrupt_after_events:
                raise RecoveryInterrupted()

    coordinator = CoordinatorSimulator(
        cast(dict[int, str], demo_state.coordinator_decisions)
    )
    try:
        result = RecoveryManager().recover(
            demo_state.log_path,
            demo_state.snapshot_path,
            collect,
            coordinator.resolve,
        )
    except RecoveryInterrupted:
        demo_state.node_statuses[target_node] = "CRASHED"
        demo_state.recovery_interrupted = True
        demo_state.recovery_interrupted_message = (
            f"Recovery interrupted after {recovery_event_count} recovery events"
        )
        await manager.broadcast(
            {
                "type": "recovery_interrupted",
                "message": demo_state.recovery_interrupted_message,
                "events_seen": recovery_event_count,
            }
        )
        await manager.broadcast(node_status(target_node, "CRASHED", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
        return {
            **status(),
            "recovery": {
                "interrupted": True,
                "events_seen": recovery_event_count,
                "message": demo_state.recovery_interrupted_message,
            },
        }

    demo_state.checkpoint_failure_detected = result.checkpoint_failure_detected
    demo_state.checkpoint_failure_message = ""
    demo_state.recovery_interrupted = False
    demo_state.recovery_interrupted_message = ""
    for event in events:
        await broadcast_event(event)
        if event.get("type") in {
            "recovery_pass",
            "recovery_record",
            "in_doubt_txn",
            "coordinator_query",
            "coordinator_decision",
            "checkpoint_failure",
        }:
            await _demo_event_pause()

    demo_state.node_statuses[target_node] = "CONSISTENT"
    await manager.broadcast(node_status(target_node, "CONSISTENT", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
    return {
        **status(),
        "recovery": {
            "rto_seconds": result.rto_seconds,
            "redo_lsn": result.redo_lsn,
            "records_scanned": result.records_scanned,
            "records_redone": result.records_redone,
            "records_undone": result.records_undone,
            "in_doubt_txns": len(result.in_doubt),
            "checkpoint_failure_detected": result.checkpoint_failure_detected,
            "coordinator_decisions": result.coordinator_decisions,
        },
    }


@router.get("/recent-log")
def recent_log(limit: int = 25) -> dict:
    records = list(iter_log_records(demo_state.log_path)) if demo_state.log_path.exists() else []
    tail = records[-limit:]
    return {
        "records": [
            {
                "lsn": record.lsn,
                "txn_id": record.txn_id,
                "record_type": record.record_type.name,
                "page_id": record.page_id,
                "before_image": record.before_image,
                "after_image": record.after_image,
            }
            for record in tail
        ]
    }


def _reset_demo_state(
    *,
    scenario_id: str,
    title: str,
    description: str,
    expected: str,
    checkpoint_interval_min: int,
    coordinator_decisions: dict[int, str],
) -> None:
    _cancel_existing_stream()
    demo_state.scenario_id = scenario_id
    demo_state.scenario_title = title
    demo_state.scenario_description = description
    demo_state.scenario_expected = expected
    demo_state.coordinator_decisions = coordinator_decisions
    demo_state.checkpoint_interval_min = checkpoint_interval_min
    demo_state.node_statuses = {"A": "RUNNING", "B": "RUNNING", "C": "RUNNING", "COORDINATOR": "RUNNING"}
    demo_state.crashed_node = "A"
    demo_state.run_started_at = time.time()
    demo_state.crashed_at = None
    demo_state.current_txn = 0
    demo_state.current_lsn = 0
    demo_state.log_stream_generation += 1


async def _restart_log_stream() -> None:
    _cancel_existing_stream()
    demo_state.log_stream_generation += 1
    generation = demo_state.log_stream_generation
    demo_state.log_stream_task = asyncio.create_task(_stream_log_records(generation))
    await manager.broadcast(demo_log_stream_state(True, generation=generation))


async def _stop_log_stream() -> None:
    _cancel_existing_stream()
    await manager.broadcast(demo_log_stream_state(False, generation=demo_state.log_stream_generation))


def _cancel_existing_stream() -> None:
    task = demo_state.log_stream_task
    if task and not task.done():
        task.cancel()
    demo_state.log_stream_task = None


async def _stream_log_records(generation: int) -> None:
    import asyncio

    try:
        for record in iter_log_records(demo_state.log_path):
            if generation != demo_state.log_stream_generation or demo_state.crashed_at is not None:
                break
            demo_state.current_txn = record.txn_id
            demo_state.current_lsn = record.lsn
            await manager.broadcast(
                log_entry(
                    lsn=record.lsn,
                    txn_id=record.txn_id,
                    record_type=record.record_type.name,
                    node_id=record.node_id,
                    page_id=record.page_id,
                    before_image=record.before_image,
                    after_image=record.after_image,
                    redo_lsn=record.redo_lsn,
                    timestamp=record.timestamp,
                )
            )
            await asyncio.sleep(0.04)
    except asyncio.CancelledError:
        raise
    finally:
        if demo_state.log_stream_generation == generation and demo_state.log_stream_task is not None:
            demo_state.log_stream_task = None


def _refresh_current_position() -> None:
    records = list(iter_log_records(demo_state.log_path))
    if records:
        demo_state.current_txn = max(record.txn_id for record in records)
        demo_state.current_lsn = records[-1].lsn
    else:
        demo_state.current_txn = 0
        demo_state.current_lsn = 0


async def _demo_event_pause() -> None:
    import asyncio

    await asyncio.sleep(0.08)
