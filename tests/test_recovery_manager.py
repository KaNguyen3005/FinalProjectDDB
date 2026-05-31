from src.log.log_record import RecordType, WalWriter
from src.recovery.recovery_manager import RecoveryManager
from src.storage import create_snapshot, read_page, write_page


def test_recovery_redoes_committed_and_undoes_loser(tmp_path):
    snapshot = tmp_path / "db_snapshot.bin"
    log = tmp_path / "transaction_log.bin"
    create_snapshot(snapshot, 2, seed=1)
    write_page(snapshot, 0, 10)
    write_page(snapshot, 1, 20)

    writer = WalWriter(log)
    writer.append(RecordType.BEGIN_CHECKPOINT)
    writer.append(RecordType.END_CHECKPOINT, redo_lsn=1)
    writer.append(RecordType.START, txn_id=1)
    writer.append(RecordType.UPDATE, txn_id=1, page_id=0, before_image=10, after_image=15)
    writer.append(RecordType.COMMIT, txn_id=1)
    writer.append(RecordType.START, txn_id=2)
    writer.append(RecordType.UPDATE, txn_id=2, page_id=1, before_image=20, after_image=25)

    write_page(snapshot, 0, 10)
    write_page(snapshot, 1, 25)

    result = RecoveryManager().recover(log, snapshot)

    assert read_page(snapshot, 0) == 15
    assert read_page(snapshot, 1) == 20
    assert result.records_redone == 1
    assert result.records_undone == 1
    assert result.undone == {2}


def test_recovery_emits_record_level_redo_and_undo_events(tmp_path):
    snapshot = tmp_path / "db_snapshot.bin"
    log = tmp_path / "transaction_log.bin"
    create_snapshot(snapshot, 2, seed=1)
    write_page(snapshot, 0, 10)
    write_page(snapshot, 1, 20)
    events = []

    writer = WalWriter(log)
    writer.append(RecordType.BEGIN_CHECKPOINT)
    writer.append(RecordType.END_CHECKPOINT, redo_lsn=1)
    writer.append(RecordType.START, txn_id=1)
    writer.append(RecordType.UPDATE, txn_id=1, page_id=0, before_image=10, after_image=15)
    writer.append(RecordType.COMMIT, txn_id=1)
    writer.append(RecordType.START, txn_id=2)
    writer.append(RecordType.UPDATE, txn_id=2, page_id=1, before_image=20, after_image=25)

    RecoveryManager().recover(log, snapshot, events.append)

    actions = [event.get("action") for event in events if event["type"] == "recovery_record"]
    assert "REDO" in actions
    assert "UNDO" in actions


def test_recovery_flags_in_doubt_transactions(tmp_path):
    snapshot = tmp_path / "db_snapshot.bin"
    log = tmp_path / "transaction_log.bin"
    create_snapshot(snapshot, 1, seed=1)
    events = []

    writer = WalWriter(log)
    writer.append(RecordType.START, txn_id=9)
    writer.append(RecordType.PREPARE, txn_id=9)
    writer.append(RecordType.READY, txn_id=9)

    result = RecoveryManager().recover(log, snapshot, events.append)

    assert result.in_doubt == {9}
    assert any(event["type"] == "in_doubt_txn" for event in events)


def test_recovery_resolves_in_doubt_with_coordinator(tmp_path):
    snapshot = tmp_path / "db_snapshot.bin"
    log = tmp_path / "transaction_log.bin"
    create_snapshot(snapshot, 2, seed=1)
    write_page(snapshot, 0, 10)
    write_page(snapshot, 1, 20)
    events = []

    writer = WalWriter(log)
    writer.append(RecordType.BEGIN_CHECKPOINT)
    writer.append(RecordType.END_CHECKPOINT, redo_lsn=1)
    writer.append(RecordType.START, txn_id=6)
    writer.append(RecordType.UPDATE, txn_id=6, page_id=0, before_image=10, after_image=16)
    writer.append(RecordType.PREPARE, txn_id=6)
    writer.append(RecordType.READY, txn_id=6)
    writer.append(RecordType.START, txn_id=8)
    writer.append(RecordType.UPDATE, txn_id=8, page_id=1, before_image=20, after_image=28)
    writer.append(RecordType.PREPARE, txn_id=8)
    writer.append(RecordType.READY, txn_id=8)

    write_page(snapshot, 0, 10)
    write_page(snapshot, 1, 28)

    result = RecoveryManager().recover(
        log,
        snapshot,
        events.append,
        lambda txn_id: {6: "COMMIT", 8: "ABORT"}.get(txn_id),
    )

    assert read_page(snapshot, 0) == 16
    assert read_page(snapshot, 1) == 20
    assert result.coordinator_decisions == {6: "COMMIT", 8: "ABORT"}
    assert any(event["type"] == "coordinator_query" for event in events)
    assert any(event.get("decision") == "COMMIT" for event in events)
    assert any(event.get("decision") == "ABORT" for event in events)


def test_recovery_flags_incomplete_checkpoint(tmp_path):
    snapshot = tmp_path / "db_snapshot.bin"
    log = tmp_path / "transaction_log.bin"
    create_snapshot(snapshot, 1, seed=1)
    events = []

    writer = WalWriter(log)
    writer.append(RecordType.BEGIN_CHECKPOINT)
    writer.append(RecordType.END_CHECKPOINT, redo_lsn=1)
    writer.append(RecordType.START, txn_id=1)
    writer.append(RecordType.UPDATE, txn_id=1, page_id=0, before_image=10, after_image=20)
    writer.append(RecordType.BEGIN_CHECKPOINT)

    result = RecoveryManager().recover(log, snapshot, events.append)

    assert result.checkpoint_failure_detected is True
    assert any(event["type"] == "checkpoint_failure" for event in events)
