from data_gen.generate_full_scale_dataset import create_large_snapshot, create_large_wal
from data_gen.generate_full_scale_dataset import align_up
from src.log.log_record import LogRecord, iter_log_records


def test_full_scale_dataset_generators_create_requested_sizes(tmp_path):
    snapshot = tmp_path / "db_snapshot.bin"
    log = tmp_path / "transaction_log.bin"

    create_large_snapshot(snapshot, 1024)
    create_large_wal(log, 4096)

    assert snapshot.stat().st_size == 1024
    assert log.stat().st_size == align_up(4096, LogRecord.SIZE)
    records = list(iter_log_records(log))
    assert len(records) > 0
