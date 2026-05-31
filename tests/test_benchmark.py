import csv
import json

from benchmark.benchmark_runner import run_single_benchmark, run_single_full_scale_benchmark, write_raw_result
from benchmark.chart_generator import generate_charts
from benchmark.cost_model import estimate_recovery_cost
from benchmark.stats_analyzer import analyze_raw_dir, percentile, summarize_results
from data_gen.generate_full_scale_dataset import create_large_snapshot, create_large_wal


def test_cost_model_grows_with_interval():
    short = estimate_recovery_cost(1, 10.0)
    long = estimate_recovery_cost(10, 10.0)

    assert long["io"] > short["io"]
    assert long["cpu"] > short["cpu"]
    assert long["theory_rto_s"] > short["theory_rto_s"]


def test_stats_analyzer_computes_summary():
    rows = summarize_results(
        [
            {"interval_min": 1, "rto_seconds": 1.0},
            {"interval_min": 1, "rto_seconds": 2.0},
            {"interval_min": 1, "rto_seconds": 3.0},
        ]
    )

    assert rows[0]["interval_min"] == 1.0
    assert rows[0]["mean_s"] == 2.0
    assert rows[0]["median_s"] == 2.0
    assert rows[0]["p99_s"] == percentile([1.0, 2.0, 3.0], 0.99)


def test_analyze_raw_dir_writes_summary_csv(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for run, rto in enumerate([0.1, 0.2], start=1):
        path = raw_dir / f"rto_interval_1min_run_{run}.json"
        path.write_text(json.dumps({"interval_min": 1, "rto_seconds": rto}), encoding="utf-8")

    output = tmp_path / "summary.csv"
    analyze_raw_dir(raw_dir, output)

    with output.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 1
    assert rows[0]["interval_min"] == "1.0"


def test_single_benchmark_run_can_write_raw_result(tmp_path):
    result = run_single_benchmark(
        interval_min=1,
        run=1,
        seed=42,
        transactions=10,
        pages=5,
        work_dir=tmp_path / "work",
    )
    output = write_raw_result(result, tmp_path / "raw")

    assert result.interval_min == 1
    assert result.rto_seconds >= 0
    assert output.exists()


def test_full_scale_benchmark_uses_existing_dataset(tmp_path):
    dataset_dir = tmp_path / "full_scale"
    create_large_snapshot(dataset_dir / "db_snapshot.bin", 1024)
    create_large_wal(dataset_dir / "transaction_log.bin", 4096)

    result = run_single_full_scale_benchmark(
        interval_min=1,
        run=1,
        seed=42,
        dataset_dir=dataset_dir,
        max_interval_min=30,
    )

    assert result.dataset_mode == "full_scale"
    assert result.source_snapshot_bytes == 1024
    assert result.source_log_bytes >= 4096
    assert result.records_scanned > 0
    assert result.scanned_log_bytes < result.source_log_bytes


def test_chart_generator_writes_svg_outputs(tmp_path):
    summary = tmp_path / "summary.csv"
    summary.write_text(
        "\n".join(
            [
                "interval_min,mean_s,median_s,p99_s,std_s,io_cost,cpu_cost,comm_cost,theory_rto_s",
                "1,0.1,0.1,0.2,0.01,10,5,2,0.1",
                "2,0.3,0.25,0.4,0.02,20,10,2,0.2",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    outputs = generate_charts(summary, tmp_path / "charts")

    assert [path.name for path in outputs] == [
        "rto_vs_interval.svg",
        "cost_breakdown.svg",
        "rto_heatmap.svg",
    ]
    assert all(path.exists() for path in outputs)
    assert "<svg" in outputs[0].read_text(encoding="utf-8")
