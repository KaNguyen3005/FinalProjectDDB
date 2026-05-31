from src.log.log_record import LogRecord, RecordType, WalWriter, iter_log_records


def test_log_record_round_trip():
    record = LogRecord.create(
        RecordType.UPDATE,
        42,
        txn_id=7,
        page_id=3,
        before_image=10,
        after_image=11,
        node_id="B",
    )

    decoded = LogRecord.unpack(record.pack())

    assert decoded == record


def test_wal_writer_appends_fixed_size_records(tmp_path):
    path = tmp_path / "transaction_log.bin"
    writer = WalWriter(path)

    writer.append(RecordType.START, txn_id=1)
    writer.append(RecordType.UPDATE, txn_id=1, page_id=2, before_image=0, after_image=99)
    writer.append(RecordType.COMMIT, txn_id=1)

    records = list(iter_log_records(path))

    assert path.stat().st_size == LogRecord.SIZE * 3
    assert [record.record_type for record in records] == [
        RecordType.START,
        RecordType.UPDATE,
        RecordType.COMMIT,
    ]
    assert [record.lsn for record in records] == [1, 2, 3]
