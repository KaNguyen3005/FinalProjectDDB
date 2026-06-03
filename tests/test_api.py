import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.app import app
from api.state import ROOT
from api.routers import demo as demo_router
from src.storage import create_snapshot


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ui_pages_are_served():
    for path, marker in [
        ("/demo", "RTO Disaster Recovery"),
        ("/benchmark", "RTO Benchmark Results"),
        ("/logs", "WAL Log Inspector"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert marker in response.text

    demo = client.get("/demo")
    assert demo.text.count(">PRIMARY<") == 3
    assert "Coordinator" in demo.text
    assert "crash-target" in demo.text

    benchmark = client.get("/benchmark")
    assert "Mean" in benchmark.text
    assert "Median" in benchmark.text
    assert "P99" in benchmark.text
    assert "IO" in benchmark.text
    assert "CPU" in benchmark.text
    assert "COMM" in benchmark.text


def test_ui_assets_are_served():
    demo_html = client.get("/demo")
    css = client.get("/css/base.css")
    js = client.get("/js/demo.js")
    benchmark_js = client.get("/js/benchmark.js")

    assert demo_html.status_code == 200
    assert "Crash Selected Node" in demo_html.text
    assert "crash-target" in demo_html.text
    assert css.status_code == 200
    assert "--bg-primary" in css.text
    assert js.status_code == 200
    assert "btn-crash" in js.text
    assert "btn-auto-demo" in js.text
    assert "btn-checkpoint-failure" in js.text
    assert "btn-recover-interrupt" in js.text
    assert "log_entry" in js.text
    assert benchmark_js.status_code == 200
    assert "1, 2, 5, 10, 20, 30" in benchmark_js.text
    assert 'dataset_mode: "full_scale"' in benchmark_js.text


def test_demo_config_crash_recover_flow():
    config = {
        "checkpoint_interval_min": 1,
        "transactions": 20,
        "pages": 10,
        "seed": 42,
    }

    configured = client.post("/api/demo/config", json=config)
    crashed = client.post("/api/demo/crash")
    recovered = client.post("/api/demo/recover")

    assert configured.status_code == 200
    assert crashed.status_code == 200
    assert recovered.status_code == 200
    assert crashed.json()["run_elapsed_seconds"] >= 0
    assert crashed.json()["crashed_at"] >= crashed.json()["run_started_at"]
    assert recovered.json()["nodes"]["A"] == "CONSISTENT"
    assert "rto_seconds" in recovered.json()["recovery"]


def test_demo_recent_log_includes_recovery_events_after_recover():
    client.post(
        "/api/demo/config",
        json={"checkpoint_interval_min": 1, "transactions": 20, "pages": 10, "seed": 42},
    )
    client.post("/api/demo/crash")
    recovered = client.post("/api/demo/recover")
    recent_log = client.get("/api/demo/recent-log?limit=500")

    event_types = [event["type"] for event in recent_log.json()["events"]]
    assert recovered.status_code == 200
    assert "log_entry" in event_types
    assert "recovery_pass" in event_types
    assert "recovery_record" in event_types
    assert "rto_complete" in event_types


def test_demo_config_creates_new_log_file_for_each_apply():
    first = client.post(
        "/api/demo/config",
        json={"checkpoint_interval_min": 1, "transactions": 5, "pages": 5, "seed": 11},
    )
    first_body = first.json()
    first_log = ROOT / first_body["log_path"]
    first_size = first_log.stat().st_size

    second = client.post(
        "/api/demo/config",
        json={"checkpoint_interval_min": 2, "transactions": 6, "pages": 5, "seed": 12},
    )
    second_body = second.json()
    second_log = ROOT / second_body["log_path"]

    assert first.status_code == 200
    assert second.status_code == 200
    assert first_body["run_id"] != second_body["run_id"]
    assert first_log != second_log
    assert first_log.exists()
    assert second_log.exists()
    assert first_log.stat().st_size == first_size


def test_demo_log_stream_does_not_move_current_lsn_backwards(monkeypatch):
    record = SimpleNamespace(
        lsn=1,
        txn_id=7,
        record_type=SimpleNamespace(name="START"),
        node_id="A",
        page_id=None,
        before_image=-1,
        after_image=-1,
        redo_lsn=-1,
        timestamp=0.0,
    )
    broadcasted = []

    async def fake_broadcast(event):
        broadcasted.append(event)

    monkeypatch.setattr(demo_router, "iter_log_records", lambda path: [record])
    monkeypatch.setattr(demo_router.manager, "broadcast", fake_broadcast)

    demo_router.demo_state.current_lsn = 999
    demo_router.demo_state.current_txn = 88
    demo_router.demo_state.stream_lsn = 0
    demo_router.demo_state.stream_txn = 0
    demo_router.demo_state.crashed_at = None
    demo_router.demo_state.log_stream_task = None
    demo_router.demo_state.log_stream_generation = 123

    asyncio.run(demo_router._stream_log_records(123))

    assert demo_router.demo_state.current_lsn == 999
    assert demo_router.demo_state.current_txn == 88
    assert demo_router.demo_state.stream_lsn == 1
    assert demo_router.demo_state.stream_txn == 7
    assert broadcasted[0]["type"] == "log_entry"


def test_demo_log_stream_starts_at_recovery_redo_lsn(monkeypatch):
    client.post(
        "/api/demo/config",
        json={"checkpoint_interval_min": 1, "transactions": 20, "pages": 10, "seed": 42},
    )
    start_lsn = demo_router._recovery_stream_start_lsn()
    broadcasted = []

    async def fake_broadcast(event):
        broadcasted.append(event)

    monkeypatch.setattr(demo_router.manager, "broadcast", fake_broadcast)
    demo_router.demo_state.live_events = []
    demo_router.demo_state.crashed_at = None
    demo_router.demo_state.log_stream_task = None
    demo_router.demo_state.log_stream_generation = 456

    asyncio.run(demo_router._stream_log_records(456, start_lsn=start_lsn))

    log_entries = [event for event in broadcasted if event["type"] == "log_entry"]
    assert log_entries
    assert log_entries[0]["lsn"] == start_lsn
    assert all(event["lsn"] >= start_lsn for event in log_entries)


def test_demo_log_stream_appends_new_records_without_repeating_transactions(monkeypatch):
    records = [
        SimpleNamespace(
            lsn=10,
            txn_id=1,
            record_type=SimpleNamespace(name="START"),
            node_id="A",
            page_id=None,
            before_image=-1,
            after_image=-1,
            redo_lsn=-1,
            timestamp=0.0,
        ),
        SimpleNamespace(
            lsn=11,
            txn_id=1,
            record_type=SimpleNamespace(name="UPDATE"),
            node_id="A",
            page_id=3,
            before_image=100,
            after_image=101,
            redo_lsn=-1,
            timestamp=0.0,
        ),
    ]
    broadcasted = []

    async def fake_broadcast(event):
        broadcasted.append(event)

    appended_txn = {"next_txn": 2, "next_lsn": 12}

    def fake_append_live_transaction():
        txn_id = appended_txn["next_txn"]
        lsn = appended_txn["next_lsn"]
        appended_txn["next_txn"] += 1
        appended_txn["next_lsn"] += 2
        return [
            SimpleNamespace(
                lsn=lsn,
                txn_id=txn_id,
                record_type=SimpleNamespace(name="START"),
                node_id="A",
                page_id=None,
                before_image=-1,
                after_image=-1,
                redo_lsn=-1,
                timestamp=0.0,
            ),
            SimpleNamespace(
                lsn=lsn + 1,
                txn_id=txn_id,
                record_type=SimpleNamespace(name="COMMIT"),
                node_id="A",
                page_id=None,
                before_image=-1,
                after_image=-1,
                redo_lsn=-1,
                timestamp=0.0,
            ),
        ]

    async def run_stream_briefly():
        demo_router.demo_state.crashed_at = None
        demo_router.demo_state.log_stream_generation = 789
        task = asyncio.create_task(
            demo_router._stream_log_records(789, start_lsn=10, append_live_workload=True)
        )
        await asyncio.sleep(0.34)
        assert not task.done()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    monkeypatch.setattr(demo_router, "iter_log_records", lambda path: records)
    monkeypatch.setattr(demo_router.manager, "broadcast", fake_broadcast)
    monkeypatch.setattr(demo_router, "_append_live_transaction", fake_append_live_transaction)

    asyncio.run(run_stream_briefly())

    log_entries = [event for event in broadcasted if event["type"] == "log_entry"]
    lsn_txn_pairs = [(event["lsn"], event["txn_id"]) for event in log_entries]
    assert lsn_txn_pairs[:4] == [(10, 1), (11, 1), (12, 2), (13, 2)]
    assert len(lsn_txn_pairs) == len(set(lsn_txn_pairs))


def test_demo_live_transaction_writes_checkpoint_at_configured_interval(tmp_path):
    demo_router.demo_state.log_path = tmp_path / "transaction_log.bin"
    demo_router.demo_state.snapshot_path = tmp_path / "db_snapshot.bin"
    demo_router.demo_state.checkpoint_interval_min = 1
    demo_router.demo_state.current_txn = 9
    create_snapshot(demo_router.demo_state.snapshot_path, 4, seed=1)

    records = demo_router._append_live_transaction()
    record_types = [record.record_type.name for record in records]

    assert "BEGIN_CHECKPOINT" in record_types
    assert "END_CHECKPOINT" in record_types
    begin = next(record for record in records if record.record_type.name == "BEGIN_CHECKPOINT")
    end = next(record for record in records if record.record_type.name == "END_CHECKPOINT")
    assert end.redo_lsn == begin.lsn


def test_demo_crash_and_recover_selected_node():
    client.post(
        "/api/demo/config",
        json={"checkpoint_interval_min": 1, "transactions": 10, "pages": 5, "seed": 7},
    )
    crashed = client.post("/api/demo/crash", json={"target_node": "B"})
    recovered = client.post("/api/demo/recover")

    assert crashed.status_code == 200
    assert recovered.status_code == 200
    assert crashed.json()["nodes"]["B"] == "CRASHED"
    assert recovered.json()["nodes"]["B"] == "CONSISTENT"
    assert recovered.json()["crashed_node"] == "B"


def test_demo_scenarios_include_in_doubt_case():
    scenarios = client.get("/api/demo/scenarios")

    assert scenarios.status_code == 200
    ids = {item["id"] for item in scenarios.json()["scenarios"]}
    assert "in_doubt_2pc" in ids
    assert "checkpoint_failure" in ids

    loaded = client.post("/api/demo/scenario", json={"scenario_id": "in_doubt_2pc", "seed": 42})
    crashed = client.post("/api/demo/crash")
    recovered = client.post("/api/demo/recover")
    recent_log = client.get("/api/demo/recent-log?limit=200")

    record_types = {record["record_type"] for record in recent_log.json()["records"]}
    assert loaded.status_code == 200
    assert crashed.status_code == 200
    assert recovered.status_code == 200
    assert loaded.json()["scenario_id"] == "in_doubt_2pc"
    assert loaded.json()["coordinator_decisions"] == {"6": "COMMIT", "8": "ABORT"}
    assert "PREPARE" in record_types
    assert "READY" in record_types
    assert recovered.json()["recovery"]["in_doubt_txns"] >= 1
    assert recovered.json()["recovery"]["coordinator_decisions"] == {"6": "COMMIT", "8": "ABORT"}


def test_demo_checkpoint_failure_scenario_emits_marker():
    loaded = client.post("/api/demo/scenario", json={"scenario_id": "checkpoint_failure", "seed": 42})
    crashed = client.post("/api/demo/crash")
    recovered = client.post("/api/demo/recover")

    assert loaded.status_code == 200
    assert crashed.status_code == 200
    assert recovered.status_code == 200
    assert loaded.json()["scenario_id"] == "checkpoint_failure"
    assert recovered.json()["recovery"]["checkpoint_failure_detected"] is True


def test_demo_recovery_interrupt_endpoint_marks_crash():
    client.post("/api/demo/config", json={"checkpoint_interval_min": 1, "transactions": 20, "pages": 10, "seed": 42})
    client.post("/api/demo/crash")
    interrupted = client.post("/api/demo/recover-interrupted", json={"interrupt_after_events": 1})

    assert interrupted.status_code == 200
    body = interrupted.json()
    assert body["recovery"]["interrupted"] is True
    assert body["nodes"]["A"] == "CRASHED"
    assert "events_seen" in body["recovery"]


def test_demo_recovery_interrupt_preserves_replayed_events():
    client.post("/api/demo/config", json={"checkpoint_interval_min": 1, "transactions": 20, "pages": 10, "seed": 42})
    client.post("/api/demo/crash")
    interrupted = client.post("/api/demo/recover-interrupted", json={"interrupt_after_events": 1})
    recent_log = client.get("/api/demo/recent-log?limit=500")

    event_types = [event["type"] for event in recent_log.json()["events"]]
    assert interrupted.status_code == 200
    assert event_types.index("recovery_pass") < event_types.index("recovery_interrupted")
    assert "recovery_interrupted" in event_types


def test_logs_records_endpoint_returns_generated_records():
    client.post(
        "/api/demo/config",
        json={"checkpoint_interval_min": 1, "transactions": 5, "pages": 5, "seed": 1},
    )

    response = client.get("/api/logs/records?offset=0&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert len(body["records"]) <= 5


def test_benchmark_results_and_raw_endpoints():
    results = client.get("/api/benchmark/results")
    raw = client.get("/api/benchmark/raw/1")
    spec = client.get("/api/benchmark/spec")

    assert results.status_code == 200
    assert isinstance(results.json(), list)
    assert raw.status_code == 200
    assert isinstance(raw.json(), list)
    assert spec.status_code == 200
    assert spec.json()["required_intervals"] == [1, 2, 5, 10, 20, 30]
    assert spec.json()["required_runs_per_interval"] == 10
    assert "full_scale_log_bytes" in spec.json()
    assert "full_scale_snapshot_bytes" in spec.json()


def test_benchmark_run_endpoint_accepts_small_job():
    response = client.post(
        "/api/benchmark/run",
        json={"intervals": [1], "runs": 1, "transactions": 5, "pages": 5, "seed": 42, "dataset_mode": "generated"},
    )
    status = client.get("/api/benchmark/status")

    assert response.status_code == 200
    assert response.json()["running"] is True
    assert response.json()["dataset_mode"] == "generated"
    assert status.status_code == 200
    assert status.json()["last_error"] is None
