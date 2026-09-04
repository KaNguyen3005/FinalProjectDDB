from __future__ import annotations

"""Thuật toán crash recovery cho WAL simulator.

RecoveryManager là phần cốt lõi: đọc WAL, xác định checkpoint hợp lệ, REDO
transaction đã commit, UNDO transaction chưa hoàn tất/abort và xử lý 2PC
in-doubt transaction thông qua coordinator simulator.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.log.log_record import LogRecord, RecordType, iter_log_records
from src.storage import write_page


EventCallback = Callable[[dict], None]
CoordinatorResolver = Callable[[int], str | None]


@dataclass
class RecoveryResult:
    """Kết quả tổng hợp sau recovery để API/UI/benchmark dùng chung."""

    rto_seconds: float
    redo_lsn: int
    committed: set[int] = field(default_factory=set)
    undone: set[int] = field(default_factory=set)
    in_doubt: set[int] = field(default_factory=set)
    records_scanned: int = 0
    records_redone: int = 0
    records_undone: int = 0
    coordinator_decisions: dict[int, str] = field(default_factory=dict)
    checkpoint_failure_detected: bool = False


class RecoveryManager:
    """
    Cài đặt WAL recovery theo thuật ngữ của roadmap:
    Analysis, Partial Redo và Global Undo.

    Transaction PREPARE/READY nhưng chưa có COMMIT/ABORT sẽ là IN_DOUBT;
    recovery không tự ý undo mà hỏi coordinator nếu có.
    """

    def recover(
        self,
        log_path: str | Path,
        snapshot_path: str | Path,
        event_cb: EventCallback | None = None,
        coordinator_resolver: CoordinatorResolver | None = None,
    ) -> RecoveryResult:
        """Chạy toàn bộ recovery workflow và trả về số liệu RTO."""
        t0 = time.perf_counter()
        records = list(iter_log_records(log_path))

        # Chia recovery thành các pass rõ ràng để UI có thể replay từng pha.
        redo_lsn, txn_state, records_scanned = self._analysis_pass(records, event_cb)
        checkpoint_failure_detected = self._detect_checkpoint_failure(records, redo_lsn, event_cb)
        records_redone = self._partial_redo(records, redo_lsn, txn_state, snapshot_path, event_cb)
        records_undone, undone = self._global_undo(records, redo_lsn, txn_state, snapshot_path, event_cb)
        # In-doubt được xử lý sau REDO/UNDO thường vì nó cần quyết định coordinator.
        in_doubt = {txn_id for txn_id, state in txn_state.items() if state == "IN_DOUBT"}
        self._handle_in_doubt(in_doubt, event_cb)
        coordinator_decisions, resolved_redo, resolved_undo = self._resolve_in_doubt(
            records,
            redo_lsn,
            in_doubt,
            snapshot_path,
            coordinator_resolver,
            event_cb,
        )
        records_redone += resolved_redo
        records_undone += resolved_undo

        rto_seconds = time.perf_counter() - t0
        self._emit(
            event_cb,
            {
                "type": "rto_complete",
                "rto_seconds": rto_seconds,
                "consistent": True,
            },
        )
        return RecoveryResult(
            rto_seconds=rto_seconds,
            redo_lsn=redo_lsn,
            committed={txn_id for txn_id, state in txn_state.items() if state == "COMMITTED"},
            undone=undone,
            in_doubt=in_doubt,
            checkpoint_failure_detected=checkpoint_failure_detected,
            records_scanned=records_scanned,
            records_redone=records_redone,
            records_undone=records_undone,
            coordinator_decisions=coordinator_decisions,
        )

    def _analysis_pass(
        self,
        records: list[LogRecord],
        event_cb: EventCallback | None,
    ) -> tuple[int, dict[int, str], int]:
        """Tìm redo_lsn và phân loại transaction trong vùng sau checkpoint."""
        self._emit(event_cb, {"type": "recovery_pass", "pass": "ANALYSIS", "progress": 0.0})
        redo_lsn = self._last_checkpoint_redo_lsn(records)
        txn_state: dict[int, str] = {}
        scanned = 0

        for record in records:
            if record.lsn < redo_lsn:
                continue
            scanned += 1
            if record.txn_id == 0:
                continue
            # Trạng thái cuối cùng quyết định cách recovery xử lý transaction.
            # START mặc định là LOSER cho tới khi gặp COMMIT/ABORT/PREPARE.
            if record.record_type == RecordType.START:
                txn_state[record.txn_id] = "LOSER"
            elif record.record_type == RecordType.PREPARE:
                txn_state[record.txn_id] = "IN_DOUBT"
            elif record.record_type == RecordType.READY:
                txn_state.setdefault(record.txn_id, "IN_DOUBT")
            elif record.record_type == RecordType.COMMIT:
                txn_state[record.txn_id] = "COMMITTED"
            elif record.record_type == RecordType.ABORT:
                txn_state[record.txn_id] = "ABORTED"

        self._emit(
            event_cb,
            {
                "type": "recovery_pass",
                "pass": "ANALYSIS",
                "progress": 1.0,
                "redo_lsn": redo_lsn,
                "records_scanned": scanned,
            },
        )
        return redo_lsn, txn_state, scanned

    def _detect_checkpoint_failure(
        self,
        records: list[LogRecord],
        redo_lsn: int,
        event_cb: EventCallback | None,
    ) -> bool:
        """Phát hiện checkpoint dở dang: có BEGIN cuối nhưng thiếu END hợp lệ."""
        last_begin_lsn: int | None = None
        last_end_lsn: int | None = None

        for record in records:
            if record.record_type == RecordType.BEGIN_CHECKPOINT:
                last_begin_lsn = record.lsn
            elif record.record_type == RecordType.END_CHECKPOINT:
                last_end_lsn = record.lsn

        if last_begin_lsn is None:
            return False
        if last_end_lsn is not None and last_begin_lsn < last_end_lsn:
            return False

        self._emit(
            event_cb,
            {
                "type": "checkpoint_failure",
                "begin_lsn": last_begin_lsn,
                "redo_lsn": redo_lsn,
                "message": (
                    f"incomplete checkpoint detected at LSN {last_begin_lsn}; "
                    f"recovery falls back to END_CHECKPOINT at LSN {redo_lsn}"
                ),
            },
        )
        return True
    def _partial_redo(
        self,
        records: list[LogRecord],
        redo_lsn: int,
        txn_state: dict[int, str],
        snapshot_path: str | Path,
        event_cb: EventCallback | None,
    ) -> int:
        """REDO các UPDATE của transaction đã commit từ redo_lsn trở đi."""
        redone = 0
        for record in records:
            # Chỉ UPDATE của transaction COMMITTED mới cần redo.
            if record.lsn < redo_lsn:
                continue
            if record.record_type != RecordType.UPDATE:
                continue
            if txn_state.get(record.txn_id) != "COMMITTED":
                continue
            if record.page_id is None:
                continue
            write_page(snapshot_path, record.page_id, record.after_image)
            redone += 1
            self._emit(
                event_cb,
                {
                    "type": "recovery_record",
                    "action": "REDO",
                    "lsn": record.lsn,
                    "txn_id": record.txn_id,
                    "page_id": record.page_id,
                    "before_image": record.before_image,
                    "after_image": record.after_image,
                    "applied_image": record.after_image,
                    "message": (
                        f"REDO LSN {record.lsn}: TXN#{record.txn_id} "
                        f"page {record.page_id} -> after_image {record.after_image}"
                    ),
                },
            )

        self._emit(
            event_cb,
            {
                "type": "recovery_pass",
                "pass": "PARTIAL_REDO",
                "txns_redone": len({r.txn_id for r in records if txn_state.get(r.txn_id) == "COMMITTED"}),
                "records_redone": redone,
            },
        )
        return redone

    def _global_undo(
        self,
        records: list[LogRecord],
        redo_lsn: int,
        txn_state: dict[int, str],
        snapshot_path: str | Path,
        event_cb: EventCallback | None,
    ) -> tuple[int, set[int]]:
        """UNDO transaction aborted/loser theo thứ tự LSN giảm dần."""
        undo_txns = {
            txn_id
            for txn_id, state in txn_state.items()
            if state in {"LOSER", "ABORTED"}
        }
        undone_records = 0
        for record in reversed(records):
            # Đi ngược log để khôi phục before_image theo thứ tự rollback đúng.
            if record.lsn < redo_lsn:
                continue
            if record.record_type != RecordType.UPDATE:
                continue
            if record.txn_id not in undo_txns:
                continue
            if record.page_id is None:
                continue
            write_page(snapshot_path, record.page_id, record.before_image)
            undone_records += 1
            self._emit(
                event_cb,
                {
                    "type": "recovery_record",
                    "action": "UNDO",
                    "lsn": record.lsn,
                    "txn_id": record.txn_id,
                    "page_id": record.page_id,
                    "before_image": record.before_image,
                    "after_image": record.after_image,
                    "applied_image": record.before_image,
                    "message": (
                        f"UNDO LSN {record.lsn}: TXN#{record.txn_id} "
                        f"page {record.page_id} -> before_image {record.before_image}"
                    ),
                },
            )

        self._emit(
            event_cb,
            {
                "type": "recovery_pass",
                "pass": "GLOBAL_UNDO",
                "txns_undone": len(undo_txns),
                "records_undone": undone_records,
            },
        )
        return undone_records, undo_txns

    def _handle_in_doubt(self, txn_ids: set[int], event_cb: EventCallback | None) -> None:
        """Emit event để UI thấy transaction đang chờ quyết định coordinator."""
        for txn_id in sorted(txn_ids):
            self._emit(
                event_cb,
                {
                    "type": "in_doubt_txn",
                    "txn_id": txn_id,
                    "message": f"TXN#{txn_id} in-doubt: awaiting coordinator decision",
                },
            )

    def _resolve_in_doubt(
        self,
        records: list[LogRecord],
        redo_lsn: int,
        txn_ids: set[int],
        snapshot_path: str | Path,
        coordinator_resolver: CoordinatorResolver | None,
        event_cb: EventCallback | None,
    ) -> tuple[dict[int, str], int, int]:
        """Hỏi coordinator simulator quyết định cuối cho transaction 2PC."""
        if not txn_ids or coordinator_resolver is None:
            return {}, 0, 0

        decisions: dict[int, str] = {}
        redone = 0
        undone = 0
        for txn_id in sorted(txn_ids):
            self._emit(
                event_cb,
                {
                    "type": "coordinator_query",
                    "txn_id": txn_id,
                    "coordinator": "Coordinator Simulator",
                    "message": f"asking coordinator for TXN#{txn_id} final decision",
                },
            )
            decision = coordinator_resolver(txn_id)
            if decision not in {"COMMIT", "ABORT"}:
                self._emit(
                    event_cb,
                    {
                        "type": "coordinator_decision",
                        "txn_id": txn_id,
                        "decision": "UNKNOWN",
                        "message": f"coordinator has no final decision for TXN#{txn_id}",
                    },
                )
                continue

            decisions[txn_id] = decision
            self._emit(
                event_cb,
                {
                    "type": "coordinator_decision",
                    "txn_id": txn_id,
                    "decision": decision,
                    "message": f"coordinator decision: TXN#{txn_id} {decision}",
                },
            )

            txn_records = [
                record
                for record in records
                if record.lsn >= redo_lsn
                and record.txn_id == txn_id
                and record.record_type == RecordType.UPDATE
                and record.page_id is not None
            ]
            # COMMIT từ coordinator nghĩa là participant phải giữ/redo work.
            # ABORT từ coordinator nghĩa là rollback các UPDATE đã prepare.
            if decision == "COMMIT":
                for record in txn_records:
                    write_page(snapshot_path, record.page_id, record.after_image)
                    redone += 1
                    self._emit_coordinator_apply(event_cb, "COORDINATOR_REDO", record, record.after_image)
            else:
                for record in reversed(txn_records):
                    write_page(snapshot_path, record.page_id, record.before_image)
                    undone += 1
                    self._emit_coordinator_apply(event_cb, "COORDINATOR_UNDO", record, record.before_image)

        return decisions, redone, undone

    def _emit_coordinator_apply(
        self,
        event_cb: EventCallback | None,
        action: str,
        record: LogRecord,
        applied_image: int,
    ) -> None:
        verb = "REDO" if action.endswith("REDO") else "UNDO"
        image_name = "after_image" if verb == "REDO" else "before_image"
        self._emit(
            event_cb,
            {
                "type": "recovery_record",
                "action": action,
                "lsn": record.lsn,
                "txn_id": record.txn_id,
                "page_id": record.page_id,
                "before_image": record.before_image,
                "after_image": record.after_image,
                "applied_image": applied_image,
                "message": (
                    f"{verb} after coordinator decision LSN {record.lsn}: "
                    f"TXN#{record.txn_id} page {record.page_id} -> {image_name} {applied_image}"
                ),
            },
        )

    def _last_checkpoint_redo_lsn(self, records: list[LogRecord]) -> int:
        """Lấy redo_lsn từ END_CHECKPOINT mới nhất; không có thì scan từ đầu."""
        for record in reversed(records):
            if record.record_type == RecordType.END_CHECKPOINT:
                return record.redo_lsn or record.lsn + 1
        return 1

    def _emit(self, event_cb: EventCallback | None, event: dict) -> None:
        # event_cb là cầu nối để API thu event và WebSocket replay cho UI.
        if event_cb:
            event_cb(event)
