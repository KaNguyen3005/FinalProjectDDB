from fastapi.testclient import TestClient

from api.app import app


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
