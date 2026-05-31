from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from api.state import ROOT, benchmark_state
from api.websocket.events import benchmark_progress
from api.websocket.manager import manager
from benchmark.benchmark_runner import run_single_benchmark, run_single_full_scale_benchmark, write_raw_result
from benchmark.stats_analyzer import analyze_raw_dir


router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


class BenchmarkRunConfig(BaseModel):
    intervals: list[int] = Field(default_factory=lambda: [1, 2, 5, 10, 20, 30])
    runs: int = Field(default=10, ge=1)
    seed: int = 42
    transactions: int = Field(default=300, ge=1)
    pages: int = Field(default=250, ge=1)
    txn_rate: float = Field(default=10.0, gt=0)
    clear_existing: bool = False
    dataset_mode: str = Field(default="generated", pattern="^(generated|full_scale)$")
    full_scale_max_interval_min: int = Field(default=30, ge=1)


async def _run_benchmark_background(config: BenchmarkRunConfig) -> None:
    results_dir = ROOT / "results"
    work_dir = ROOT / "data" / "api_benchmark_runs"
    full_scale_dir = ROOT / "data" / "full_scale"
    raw_dir = results_dir / "raw"
    total = len(config.intervals) * config.runs
    completed = 0
    benchmark_state.running = True
    benchmark_state.last_error = None
    try:
        if config.clear_existing:
            await asyncio.to_thread(_clear_benchmark_outputs, raw_dir, results_dir / "summary.csv")
        for interval in config.intervals:
            for run in range(1, config.runs + 1):
                run_seed = config.seed + interval * 10_000 + run
                if config.dataset_mode == "full_scale":
                    result = await asyncio.to_thread(
                        run_single_full_scale_benchmark,
                        interval_min=interval,
                        run=run,
                        seed=run_seed,
                        dataset_dir=full_scale_dir,
                        max_interval_min=config.full_scale_max_interval_min,
                    )
                else:
                    result = await asyncio.to_thread(
                        run_single_benchmark,
                        interval_min=interval,
                        run=run,
                        seed=run_seed,
                        transactions=config.transactions,
                        pages=config.pages,
                        work_dir=work_dir,
                    )
                write_raw_result(result, raw_dir)
                completed += 1
                await manager.broadcast(
                    benchmark_progress(
                        interval,
                        run,
                        result.rto_seconds,
                        total,
                        completed_runs=completed,
                    )
                )
        await asyncio.to_thread(analyze_raw_dir, raw_dir, results_dir / "summary.csv", txn_rate=config.txn_rate)
    except Exception as exc:
        benchmark_state.last_error = str(exc)
        await manager.broadcast({"type": "benchmark_error", "message": str(exc)})
    finally:
        benchmark_state.running = False
        benchmark_state.completed_at = asyncio.get_running_loop().time()


@router.post("/run")
async def run_benchmark(config: BenchmarkRunConfig, background_tasks: BackgroundTasks) -> dict:
    if benchmark_state.running:
        raise HTTPException(status_code=409, detail="benchmark already running")
    benchmark_state.running = True
    benchmark_state.started_at = asyncio.get_running_loop().time()
    benchmark_state.completed_at = None
    background_tasks.add_task(_run_benchmark_background, config)
    return {
        "running": True,
        "intervals": config.intervals,
        "runs": config.runs,
        "dataset_mode": config.dataset_mode,
    }


@router.get("/status")
def benchmark_status() -> dict:
    return {
        "running": benchmark_state.running,
        "started_at": benchmark_state.started_at,
        "completed_at": benchmark_state.completed_at,
        "last_error": benchmark_state.last_error,
    }


@router.get("/spec")
def benchmark_spec() -> dict:
    full_scale_dir = ROOT / "data" / "full_scale"
    log_path = full_scale_dir / "transaction_log.bin"
    snapshot_path = full_scale_dir / "db_snapshot.bin"
    return {
        "required_intervals": [1, 2, 5, 10, 20, 30],
        "required_runs_per_interval": 10,
        "default_transactions": 300,
        "default_pages": 250,
        "full_scale_log_bytes": log_path.stat().st_size if log_path.exists() else 0,
        "full_scale_snapshot_bytes": snapshot_path.stat().st_size if snapshot_path.exists() else 0,
        "description": "Full project benchmark matrix from the roadmap.",
    }


@router.get("/results")
def benchmark_results() -> list[dict]:
    path = ROOT / "results" / "summary.csv"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@router.get("/raw/{interval}")
def raw_results(interval: int) -> list[dict]:
    raw_dir = ROOT / "results" / "raw"
    rows = []
    for path in sorted(raw_dir.glob(f"rto_interval_{interval}min_run_*.json")):
        with path.open("r", encoding="utf-8") as fh:
            rows.append(json.load(fh))
    return rows


def _clear_benchmark_outputs(raw_dir: Path, summary_path: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    for path in raw_dir.glob("rto_interval_*min_run_*.json"):
        path.unlink()
    summary_path.unlink(missing_ok=True)
