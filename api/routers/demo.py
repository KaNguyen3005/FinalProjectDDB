from __future__ import annotations

"""API điều phối màn hình /demo.

Router này là lớp nối giữa UI và core engine: sinh WAL/snapshot, stream live log,
giả lập crash, chạy recovery và broadcast event để browser hiển thị realtime.
"""

import asyncio
import time
from uuid import uuid4
from typing import Literal, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.state import ROOT, demo_state
from api.websocket.events import crash_event, demo_log_stream_state, log_entry, node_status
from api.websocket.manager import manager
from data_gen.demo_scenarios import generate_demo_scenario, list_scenarios
from data_gen.generate_logs import generate_logs
from src.checkpoint.checkpoint_manager import CheckpointManager
from src.coordinator import CoordinatorSimulator
from src.log.log_record import RecordType, WalWriter, iter_log_records
from src.recovery.recovery_manager import RecoveryManager
from src.storage import page_count, read_page, write_page


router = APIRouter(prefix="/api/demo", tags=["demo"])
LIVE_EVENT_LIMIT = 1_000
# Chỉ các event thuộc bề mặt Live Log/Timeline mới được lưu lại để hydrate UI.
LIVE_EVENT_TYPES = {
    "log_entry",
    "crash",
    "recovery_pass",
    "recovery_record",
    "in_doubt_txn",
    "coordinator_query",
    "coordinator_decision",
    "checkpoint_failure",
    "recovery_interrupted",
    "rto_complete",
}


class DemoConfig(BaseModel):
    """Thông số custom workload khi người dùng bấm Apply Config."""

    checkpoint_interval_min: int = Field(default=5, ge=1)
    transactions: int = Field(default=200, ge=1)
    pages: int = Field(default=100, ge=1)
    seed: int = 42


class DemoScenarioRequest(BaseModel):
    """Request load một scenario dựng sẵn."""

    scenario_id: str
    seed: int = 42


class RecoveryInterruptRequest(BaseModel):
    """Số event recovery cần phát trước khi giả lập crash lần hai."""

    interrupt_after_events: int = Field(default=4, ge=1)


class CrashRequest(BaseModel):
    """Node đích mà UI muốn crash."""

    target_node: Literal["A", "B", "C"] = "A"


@router.get("/status")
def status() -> dict:
    """Trả trạng thái điều khiển hiện tại để UI hydrate khi load trang."""
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
        "stream_txn": demo_state.stream_txn,
        "stream_lsn": demo_state.stream_lsn,
        "run_id": demo_state.run_id,
        "log_path": demo_state.log_path.relative_to(ROOT).as_posix(),
        "snapshot_path": demo_state.snapshot_path.relative_to(ROOT).as_posix(),
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
    """List curated recovery scenarios available in the UI."""
    return {"scenarios": list_scenarios()}


@router.post("/scenario")
async def load_scenario(request: DemoScenarioRequest) -> dict:
    """Sinh WAL/snapshot theo scenario dựng sẵn, ví dụ 2PC hoặc checkpoint failure."""
    # Kiểm tra scenario_id có nằm trong danh sách scenario mà backend hỗ trợ không.
    # Nếu không hợp lệ, trả 404 để frontend hiển thị lỗi rõ ràng.
    if request.scenario_id not in {scenario["id"] for scenario in list_scenarios()}:
        raise HTTPException(status_code=404, detail=f"unknown demo scenario: {request.scenario_id}")
    # Mỗi lần load scenario sẽ tạo một run mới với log_path/snapshot_path riêng.
    # Điều này tránh ghi đè WAL/snapshot của lần demo trước.
    _activate_new_run("scenario")
    try:
        # Sinh WAL và snapshot theo kịch bản dựng sẵn.
        # Ví dụ: clean recovery, heavy redo, global undo, 2PC in-doubt,
        # hoặc checkpoint failure.
        scenario = generate_demo_scenario(
            request.scenario_id,
            demo_state.log_path,
            demo_state.snapshot_path,
            seed=request.seed,
        )
    except ValueError as exc:
        # Nếu generator báo scenario không tồn tại, chuyển thành HTTP 404.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Reset state hiển thị theo metadata của scenario vừa sinh.
    # coordinator_decisions được dùng cho scenario 2PC để recovery hỏi coordinator.
    _reset_demo_state(
        scenario_id=scenario.id,
        title=scenario.title,
        description=scenario.description,
        expected=scenario.expected,
        checkpoint_interval_min=scenario.checkpoint_interval_min,
        coordinator_decisions={int(txn_id): decision for txn_id, decision in (scenario.coordinator_decisions or {}).items()},
    )
    # Xóa các trạng thái lỗi/interrupted còn sót lại từ run trước.
    demo_state.checkpoint_failure_detected = False
    demo_state.checkpoint_failure_message = ""
    demo_state.recovery_interrupted = False
    demo_state.recovery_interrupted_message = ""
    # Mặc định node A là node bị crash nếu người dùng không chọn node khác.
    demo_state.crashed_node = "A"
    # Đọc WAL vừa sinh để cập nhật current_txn/current_lsn cho UI.
    _refresh_current_position()
    # Bắt đầu stream WAL của scenario ra Live Log.
    # Scenario dựng sẵn chỉ replay WAL đã sinh, không append transaction mới.
    await _restart_log_stream()
    # Broadcast trạng thái cluster để browser cập nhật node card.
    await manager.broadcast(node_status("A", "RUNNING", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
    await manager.broadcast(node_status("COORDINATOR", "RUNNING"))
    # Trả toàn bộ trạng thái demo hiện tại cho frontend hydrate UI.
    return status()


@router.post("/config")
async def configure(config: DemoConfig) -> dict:
    """Sinh workload custom từ checkpoint interval và bắt đầu live append."""
    _activate_new_run("custom")
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
    # Lần đầu tạo WAL có sẵn checkpoint theo interval; sau đó live stream append thêm.
    generate_logs(
        demo_state.log_path,
        demo_state.snapshot_path,
        transactions=config.transactions,
        checkpoint_every=max(1, config.checkpoint_interval_min * 10),
        seed=config.seed,
        pages=config.pages,
    )
    _refresh_current_position()
    await _restart_log_stream(append_live_workload=True)
    await manager.broadcast(node_status("A", "RUNNING", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
    await manager.broadcast(node_status("COORDINATOR", "RUNNING"))
    return status()


@router.post("/crash")
async def crash(request: CrashRequest | None = None) -> dict:
    """Dừng live log và đánh dấu node bị crash."""
    if not demo_state.log_path.exists() or not demo_state.snapshot_path.exists():
        await configure(DemoConfig(checkpoint_interval_min=demo_state.checkpoint_interval_min))

    target_node = request.target_node if request else "A"
    demo_state.crashed_node = target_node
    await _stop_log_stream()
    demo_state.node_statuses[target_node] = "CRASHED"
    demo_state.crashed_at = time.time()
    run_elapsed_seconds = demo_state.crashed_at - demo_state.run_started_at
    await _publish_live_event(
        crash_event(target_node, demo_state.crashed_at, run_elapsed_seconds=run_elapsed_seconds)
    )
    await manager.broadcast(node_status(target_node, "CRASHED", txn=demo_state.current_txn, lsn=demo_state.current_lsn))
    return status()


@router.post("/recover")
async def recover() -> dict:
    """Recover the crashed node using the full event playback."""
    return await _run_recovery()


@router.post("/recover-interrupted")
async def recover_interrupted(request: RecoveryInterruptRequest | None = None) -> dict:
    """Run recovery but interrupt it after a few events for demo purposes."""
    interrupt_after_events = (request.interrupt_after_events if request else 4)
    return await _run_recovery(interrupt_after_events=interrupt_after_events)


async def _run_recovery(*, interrupt_after_events: int | None = None) -> dict:
    """Chạy recovery, thu event rồi replay ra WebSocket theo nhịp dễ quan sát."""
    if not demo_state.log_path.exists() or not demo_state.snapshot_path.exists():
        await configure(DemoConfig(checkpoint_interval_min=demo_state.checkpoint_interval_min))

    target_node = demo_state.crashed_node or "A"
    await _stop_log_stream()
    demo_state.node_statuses[target_node] = "RECOVERING"
    await manager.broadcast(node_status(target_node, "RECOVERING", txn=demo_state.current_txn, lsn=demo_state.current_lsn))

    events = []
    recovery_event_count = 0

    class RecoveryInterrupted(RuntimeError):
        pass

    def collect(event: dict) -> None:
        """Thu event từ RecoveryManager và có thể ngắt để demo crash khi recovery."""
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
        # Recovery chạy đồng bộ trên WAL/snapshot hiện tại; event được collect trước.
        result = RecoveryManager().recover(
            demo_state.log_path,
            demo_state.snapshot_path,
            collect,
            coordinator.resolve,
        )
    except RecoveryInterrupted:
        # Khi demo interrupted recovery, vẫn replay các event đã xảy ra trước khi báo crash.
        demo_state.node_statuses[target_node] = "CRASHED"
        demo_state.recovery_interrupted = True
        demo_state.recovery_interrupted_message = (
            f"Recovery interrupted after {recovery_event_count} recovery events"
        )
        for event in events:
            await _publish_live_event(event)
            if event.get("type") in {
                "recovery_pass",
                "recovery_record",
                "in_doubt_txn",
                "coordinator_query",
                "coordinator_decision",
                "checkpoint_failure",
            }:
                await _demo_event_pause()
        await _publish_live_event(
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
        await _publish_live_event(event)
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
    """Trả lịch sử live event để UI refresh/reconnect không mất recovery log."""
    live_tail = demo_state.live_events[-limit:]
    records = list(iter_log_records(demo_state.log_path)) if demo_state.log_path.exists() else []
    tail = records[-limit:]
    return {
        "events": live_tail,
        "records": [
            {
                "type": "log_entry",
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
    """Reset state mỗi khi Apply Config hoặc Load Scenario tạo run mới."""
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
    demo_state.stream_txn = 0
    demo_state.stream_lsn = 0
    demo_state.live_events = []
    demo_state.log_stream_generation += 1


def _activate_new_run(kind: str) -> None:
    """Tạo đường dẫn WAL/snapshot mới để các lần Apply Config không đè nhau."""
    run_id = f"{int(time.time() * 1000)}-{kind}-{uuid4().hex[:8]}"
    run_dir = ROOT / "data" / "api_demo" / "runs" / run_id
    demo_state.run_id = run_id
    demo_state.log_path = run_dir / "transaction_log.bin"
    demo_state.snapshot_path = run_dir / "db_snapshot.bin"


async def _restart_log_stream(*, append_live_workload: bool = False) -> None:
    """Khởi động background task stream WAL ra UI."""
    _cancel_existing_stream()
    demo_state.log_stream_generation += 1
    generation = demo_state.log_stream_generation
    demo_state.log_stream_task = asyncio.create_task(
        _stream_log_records(
            generation,
            start_lsn=_recovery_stream_start_lsn(),
            append_live_workload=append_live_workload,
        )
    )
    await manager.broadcast(demo_log_stream_state(True, generation=generation))


async def _stop_log_stream() -> None:
    """Hủy stream hiện tại khi crash/recover hoặc khi load run mới."""
    _cancel_existing_stream()
    await manager.broadcast(demo_log_stream_state(False, generation=demo_state.log_stream_generation))


def _cancel_existing_stream() -> None:
    """Cancel task cũ; generation guard ngăn event cũ lọt vào run mới."""
    task = demo_state.log_stream_task
    if task and not task.done():
        task.cancel()
    demo_state.log_stream_task = None


async def _stream_log_records(
    generation: int,
    *,
    start_lsn: int = 1,
    append_live_workload: bool = False,
) -> None:
    """Stream WAL; riêng custom mode sẽ append transaction mới để log chạy liên tục."""
    import asyncio

    try:
        # Phần đầu stream lại vùng WAL mà recovery sẽ dùng, tránh lệch LSN với recovery log.
        records = [record for record in iter_log_records(demo_state.log_path) if record.lsn >= start_lsn]
        for record in records:
            if generation != demo_state.log_stream_generation or demo_state.crashed_at is not None:
                break
            demo_state.stream_txn = record.txn_id
            demo_state.stream_lsn = record.lsn
            await _publish_live_event(
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
        if not append_live_workload:
            return
        # Custom mode tiếp tục sinh transaction mới thật vào WAL thay vì lặp record cũ.
        while generation == demo_state.log_stream_generation and demo_state.crashed_at is None:
            for record in _append_live_transaction():
                if generation != demo_state.log_stream_generation or demo_state.crashed_at is not None:
                    break
                demo_state.stream_txn = record.txn_id
                demo_state.stream_lsn = record.lsn
                demo_state.current_txn = max(demo_state.current_txn, record.txn_id)
                demo_state.current_lsn = max(demo_state.current_lsn, record.lsn)
                await _publish_live_event(
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
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        raise
    finally:
        if demo_state.log_stream_generation == generation and demo_state.log_stream_task is not None:
            demo_state.log_stream_task = None


def _refresh_current_position() -> None:
    """Cập nhật current_txn/current_lsn từ tail WAL sau khi sinh dữ liệu."""
    records = list(iter_log_records(demo_state.log_path))
    if records:
        demo_state.current_txn = max(record.txn_id for record in records)
        demo_state.current_lsn = records[-1].lsn
        demo_state.stream_txn = 0
        demo_state.stream_lsn = 0
    else:
        demo_state.current_txn = 0
        demo_state.current_lsn = 0
        demo_state.stream_txn = 0
        demo_state.stream_lsn = 0


def _recovery_stream_start_lsn() -> int:
    """Tìm redo_lsn từ checkpoint mới nhất để Live Log khớp Recovery Log."""
    if not demo_state.log_path.exists():
        return 1
    records = list(iter_log_records(demo_state.log_path))
    for record in reversed(records):
        if record.record_type.name == "END_CHECKPOINT":
            return record.redo_lsn or record.lsn + 1
    return 1


def _append_live_transaction() -> list:
    """Append transaction mới vào WAL để custom live log chạy tiếp mà không duplicate."""
    pages = max(1, page_count(demo_state.snapshot_path))
    txn_id = demo_state.current_txn + 1
    writer = WalWriter(demo_state.log_path)
    records = [writer.append(RecordType.START, txn_id=txn_id)]
    updates = 1 + (txn_id % 3)
    for index in range(updates):
        page_id = (txn_id * 11 + index * 7) % pages
        before = read_page(demo_state.snapshot_path, page_id)
        after = before + 10 + (txn_id % 17) + index
        records.append(
            writer.append(
                RecordType.UPDATE,
                txn_id=txn_id,
                page_id=page_id,
                before_image=before,
                after_image=after,
            )
        )
        write_page(demo_state.snapshot_path, page_id, after)
    # Outcome deterministic giúp demo dễ lặp lại: đa số commit, một phần abort/2PC.
    decision = txn_id % 10
    if decision < 7:
        records.append(writer.append(RecordType.COMMIT, txn_id=txn_id))
    elif decision < 9:
        records.append(writer.append(RecordType.ABORT, txn_id=txn_id))
    else:
        records.append(writer.append(RecordType.PREPARE, txn_id=txn_id))
        records.append(writer.append(RecordType.READY, txn_id=txn_id))
    # Interval trên UI được quy đổi sang số transaction giữa hai checkpoint.
    checkpoint_every = max(1, demo_state.checkpoint_interval_min * 10)
    if txn_id % checkpoint_every == 0:
        begin_lsn, end_lsn = CheckpointManager(writer).write_checkpoint()
        checkpoint_records = [
            record
            for record in iter_log_records(demo_state.log_path)
            if record.lsn in {begin_lsn, end_lsn}
        ]
        records.extend(checkpoint_records)
    return records


async def _demo_event_pause() -> None:
    """Small UI pacing delay between recovery events."""
    import asyncio

    await asyncio.sleep(0.08)


async def _publish_live_event(event: dict) -> None:
    """Lưu event vào history rồi broadcast để UI realtime và hydrate đều đồng bộ."""
    if event.get("type") in LIVE_EVENT_TYPES:
        demo_state.live_events.append(event)
        if len(demo_state.live_events) > LIVE_EVENT_LIMIT:
            del demo_state.live_events[: len(demo_state.live_events) - LIVE_EVENT_LIMIT]
    await manager.broadcast(event)
