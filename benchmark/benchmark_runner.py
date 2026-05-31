from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.stats_analyzer import analyze_raw_dir
from data_gen.generate_logs import generate_logs
from src.integrity.integrity_checker import sha256_file
from src.log.log_record import LogRecord, RecordType
from src.recovery.recovery_manager import RecoveryManager


@dataclass
class BenchmarkRunResult:
    """Serializable result for one benchmark run."""

    interval_min: int
    run: int
    seed: int
    rto_seconds: float
    redo_lsn: int
    records_scanned: int
    records_redone: int
    records_undone: int
    in_doubt_txns: int
    snapshot_sha256_before: str
    snapshot_sha256_after: str
    started_at: float
    completed_at: float
    dataset_mode: str = "generated"
    source_log_bytes: int = 0
    source_snapshot_bytes: int = 0
    scanned_log_bytes: int = 0
    metadata: dict[str, int | float | str] = field(default_factory=dict)


def run_single_benchmark(
    *,
    interval_min: int,
    run: int,
    seed: int,
    transactions: int,
    pages: int,
    work_dir: Path,
) -> BenchmarkRunResult:
    """Generate a fresh workload, recover it, and capture measured RTO."""
    run_dir = work_dir / f"interval_{interval_min}min_run_{run}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "transaction_log.bin"
    snapshot_path = run_dir / "db_snapshot.bin"

    checkpoint_every = max(1, interval_min * 10)
    started_at = time.time()
    generate_logs(
        log_path,
        snapshot_path,
        transactions=transactions,
        checkpoint_every=checkpoint_every,
        seed=seed,
        pages=pages,
    )

    before = sha256_file(snapshot_path)
    recovery = RecoveryManager().recover(log_path, snapshot_path)
    after = sha256_file(snapshot_path)
    completed_at = time.time()

    return BenchmarkRunResult(
        interval_min=interval_min,
        run=run,
        seed=seed,
        rto_seconds=recovery.rto_seconds,
        redo_lsn=recovery.redo_lsn,
        records_scanned=recovery.records_scanned,
        records_redone=recovery.records_redone,
        records_undone=recovery.records_undone,
        in_doubt_txns=len(recovery.in_doubt),
        snapshot_sha256_before=before,
        snapshot_sha256_after=after,
        started_at=started_at,
        completed_at=completed_at,
    )


def run_single_full_scale_benchmark(
    *,
    interval_min: int,
    run: int,
    seed: int,
    dataset_dir: Path,
    max_interval_min: int = 30,
) -> BenchmarkRunResult:
    """Benchmark a scan window over a pre-generated full-scale dataset."""
    log_path = dataset_dir / "transaction_log.bin"
    snapshot_path = dataset_dir / "db_snapshot.bin"
    if not log_path.exists() or not snapshot_path.exists():
        raise FileNotFoundError(f"full-scale dataset not found under {dataset_dir}")

    log_size = log_path.stat().st_size
    snapshot_size = snapshot_path.stat().st_size
    scan_bytes = _aligned_scan_bytes(log_size, interval_min, max_interval_min)

    started_at = time.time()
    stats = _scan_full_scale_window(log_path, scan_bytes, seed=seed + run)
    completed_at = time.time()

    return BenchmarkRunResult(
        interval_min=interval_min,
        run=run,
        seed=seed,
        rto_seconds=completed_at - started_at,
        redo_lsn=1,
        records_scanned=stats["records_scanned"],
        records_redone=stats["records_redone"],
        records_undone=stats["records_undone"],
        in_doubt_txns=stats["in_doubt_txns"],
        snapshot_sha256_before=f"size:{snapshot_size}",
        snapshot_sha256_after=f"size:{snapshot_size}",
        started_at=started_at,
        completed_at=completed_at,
        dataset_mode="full_scale",
        source_log_bytes=log_size,
        source_snapshot_bytes=snapshot_size,
        scanned_log_bytes=scan_bytes,
        metadata={
            "max_interval_min": max_interval_min,
            "committed_txns": stats["committed_txns"],
            "aborted_txns": stats["aborted_txns"],
        },
    )


def _aligned_scan_bytes(log_size: int, interval_min: int, max_interval_min: int) -> int:
    """Scale a log scan window by interval and align it to WAL record size."""
    target = int(log_size * (interval_min / max_interval_min))
    target = max(LogRecord.SIZE, target)
    target -= target % LogRecord.SIZE
    return min(log_size, max(LogRecord.SIZE, target))


def _scan_full_scale_window(log_path: Path, scan_bytes: int, *, seed: int) -> dict[str, int]:
    """Scan the tail of a large WAL and estimate recovery work from records."""
    committed: set[int] = set()
    aborted: set[int] = set()
    prepared: set[int] = set()
    active: set[int] = set()
    update_counts: dict[int, int] = {}
    records_scanned = 0

    start_offset = max(0, log_path.stat().st_size - scan_bytes)
    start_offset -= start_offset % LogRecord.SIZE
    with log_path.open("rb") as fh:
        fh.seek(start_offset)
        remaining = scan_bytes
        while remaining >= LogRecord.SIZE:
            # Read exact record-sized chunks so unpacking stays aligned.
            chunk = fh.read(LogRecord.SIZE)
            if len(chunk) != LogRecord.SIZE:
                break
            remaining -= LogRecord.SIZE
            record = LogRecord.unpack(chunk)
            records_scanned += 1
            if record.txn_id == 0:
                continue
            if record.record_type == RecordType.START:
                active.add(record.txn_id)
            elif record.record_type == RecordType.UPDATE:
                update_counts[record.txn_id] = update_counts.get(record.txn_id, 0) + 1
            elif record.record_type == RecordType.COMMIT:
                committed.add(record.txn_id)
                active.discard(record.txn_id)
            elif record.record_type == RecordType.ABORT:
                aborted.add(record.txn_id)
                active.discard(record.txn_id)
            elif record.record_type in {RecordType.PREPARE, RecordType.READY}:
                prepared.add(record.txn_id)

    in_doubt = prepared - committed - aborted
    loser = active - committed - aborted - in_doubt
    records_redone = sum(update_counts.get(txn_id, 0) for txn_id in committed)
    records_undone = sum(update_counts.get(txn_id, 0) for txn_id in aborted | loser)
    return {
        "records_scanned": records_scanned,
        "records_redone": records_redone,
        "records_undone": records_undone,
        "in_doubt_txns": len(in_doubt),
        "committed_txns": len(committed),
        "aborted_txns": len(aborted),
    }


def write_raw_result(result: BenchmarkRunResult, raw_dir: Path) -> Path:
    """Write one run result as JSON for later statistical aggregation."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"rto_interval_{result.interval_min}min_run_{result.run}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(asdict(result), fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


def run_benchmark_matrix(
    *,
    intervals: list[int],
    runs: int,
    seed: int,
    transactions: int,
    pages: int,
    results_dir: Path,
    work_dir: Path,
    txn_rate: float,
    clear_existing: bool = True,
    dataset_mode: str = "generated",
    full_scale_dir: Path = Path("data/full_scale"),
    full_scale_max_interval_min: int = 30,
) -> list[dict[str, float]]:
    """Run every checkpoint interval and aggregate raw results into CSV."""
    raw_dir = results_dir / "raw"
    summary_path = results_dir / "summary.csv"
    if clear_existing:
        raw_dir.mkdir(parents=True, exist_ok=True)
        for path in raw_dir.glob("rto_interval_*min_run_*.json"):
            path.unlink()
        summary_path.unlink(missing_ok=True)

    total = len(intervals) * runs
    completed = 0
    for interval in intervals:
        for run in range(1, runs + 1):
            # Deterministic but unique seed per matrix cell/run.
            run_seed = seed + interval * 10_000 + run
            if dataset_mode == "full_scale":
                result = run_single_full_scale_benchmark(
                    interval_min=interval,
                    run=run,
                    seed=run_seed,
                    dataset_dir=full_scale_dir,
                    max_interval_min=full_scale_max_interval_min,
                )
            else:
                result = run_single_benchmark(
                    interval_min=interval,
                    run=run,
                    seed=run_seed,
                    transactions=transactions,
                    pages=pages,
                    work_dir=work_dir,
                )
            write_raw_result(result, raw_dir)
            completed += 1
            print(
                f"[{completed}/{total}] interval={interval}min run={run} "
                f"rto={result.rto_seconds:.6f}s scanned={result.records_scanned}"
            )

    rows = analyze_raw_dir(raw_dir, summary_path, txn_rate=txn_rate)
    print(f"summary written: {summary_path}")
    return rows


def parse_args() -> argparse.Namespace:
    """Parse CLI options for local benchmark execution."""
    parser = argparse.ArgumentParser(description="Run RTO benchmark matrix.")
    parser.add_argument("--intervals", nargs="+", type=int, default=[1, 2, 5, 10, 20, 30])
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--transactions", type=int, default=300)
    parser.add_argument("--pages", type=int, default=250)
    parser.add_argument("--txn-rate", type=float, default=10.0)
    parser.add_argument("--dataset-mode", choices=["generated", "full_scale"], default="generated")
    parser.add_argument("--full-scale-dir", type=Path, default=Path("data/full_scale"))
    parser.add_argument("--full-scale-max-interval", type=int, default=30)
    parser.add_argument("--keep-existing", action="store_true")
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--work-dir", type=Path, default=Path("data/benchmark_runs"))
    return parser.parse_args()


def main() -> None:
    """CLI entry point."""
    args = parse_args()
    run_benchmark_matrix(
        intervals=args.intervals,
        runs=args.runs,
        seed=args.seed,
        transactions=args.transactions,
        pages=args.pages,
        results_dir=args.results_dir,
        work_dir=args.work_dir,
        txn_rate=args.txn_rate,
        clear_existing=not args.keep_existing,
        dataset_mode=args.dataset_mode,
        full_scale_dir=args.full_scale_dir,
        full_scale_max_interval_min=args.full_scale_max_interval,
    )


if __name__ == "__main__":
    main()
