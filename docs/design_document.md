# Design Document: RTO Disaster Recovery Benchmark

## Scope

This project measures how checkpoint frequency affects the Recovery Time Objective (RTO) of a crashed distributed database node. The implementation is intentionally small enough to run on a laptop, but it preserves the recovery concepts required by the roadmap:

- Write-ahead log records with before and after images.
- BEGIN_CHECKPOINT and END_CHECKPOINT markers.
- Analysis, Partial Redo, and Global Undo recovery phases.
- 2PC PREPARE/READY records and in-doubt transaction detection.
- A repeatable benchmark matrix with controlled inputs.
- A browser UI for live crash and recovery demonstration.

## Architecture

```text
Browser UI
  /demo        live crash and recovery dashboard
  /benchmark   benchmark charts and summary table
  /logs        paginated WAL inspector
      |
      | REST control/results + WebSocket events
      v
FastAPI backend
  api/routers/demo.py       crash, recover, configure demo
  api/routers/benchmark.py  background benchmark run and results
  api/routers/logs.py       WAL record inspection
  api/websocket/*           event fan-out
      |
      v
Core engine
  src/log/                  fixed-size binary WAL records
  src/storage.py            binary snapshot pages
  src/checkpoint/           checkpoint markers
  src/recovery/             Analysis, Partial Redo, Global Undo
  src/crash/                crash injection and RTO timer
      |
      v
Generated data and results
  data/                     generated WAL and snapshots
  results/raw/              per-run benchmark JSON
  results/summary.csv       aggregate statistics
  results/charts/           generated SVG report charts
```

## Recovery Flow

The recovery manager maps directly to the textbook terminology used in the roadmap.

| Step | Implementation | Textbook mapping | Purpose |
|---|---|---|---|
| 1 | Locate the latest END_CHECKPOINT redo LSN | Appendix C.6 checkpointing | Avoid scanning the full log after every crash. |
| 2 | Analysis pass builds transaction states | Appendix C.6 WAL recovery | Classify transactions as COMMITTED, ABORTED, LOSER, or IN_DOUBT. |
| 3 | Partial Redo reapplies committed UPDATE after images | Appendix C.6 Partial Redo | Enforce durability for committed updates after checkpoint. |
| 4 | Global Undo restores before images for loser or aborted transactions | Appendix C.6 Global Undo | Enforce atomicity for incomplete work. |
| 5 | PREPARE/READY without COMMIT/ABORT becomes IN_DOUBT | Section 5.4.3 site failure and 2PC | Do not unilaterally undo a participant that may have committed globally. |

The implementation uses an ARIES-like pass structure internally, but the externally visible event names, UI labels, and report terminology use the Partial Redo and Global Undo terms from the project roadmap.

## WAL Record Model

`src/log/log_record.py` stores fixed-size binary records. The supported record types are:

| Type | Meaning |
|---|---|
| START | Transaction begins. |
| UPDATE | Carries page id, before image, and after image. |
| COMMIT | Transaction committed; redo after images during recovery. |
| ABORT | Transaction aborted; undo before images during recovery. |
| BEGIN_CHECKPOINT | Checkpoint started. |
| END_CHECKPOINT | Dirty pages flushed; recovery can start from its redo LSN. |
| PREPARE | 2PC prepare decision was logged. |
| READY | Participant voted yes and is waiting for final decision. |

## Crash Injection Methodology

The demo path creates a repeatable WAL and snapshot for the selected checkpoint interval. A crash marks Node A as failed, records the crash timestamp, and starts the UI stopwatch. Recovery then invokes `RecoveryManager.recover()` over the current log and snapshot. The RTO measurement starts immediately before recovery work begins and stops after the snapshot is consistent and the recovery result is emitted.

## Variable Control

| Variable | Control strategy |
|---|---|
| Checkpoint interval | Independent variable: 1, 2, 5, 10, 20, 30 minutes in the full benchmark. |
| Randomness | Seeded generator; benchmark runner derives per-run seeds from base seed, interval, and run id. |
| Transaction count | Fixed per benchmark invocation through `--transactions`. |
| Snapshot size | Fixed per benchmark invocation through `--pages`. |
| Transaction rate for cost model | Fixed through `--txn-rate`, default 10 transactions per second. |
| Hardware and process overhead | All intervals run through the same Python engine and benchmark runner. |
| Statistical repetition | Full target is 10 runs per interval; smoke baseline may use fewer runs. |

## UI Architecture

The UI is static HTML/CSS/JavaScript served by FastAPI. REST endpoints trigger actions and fetch persisted results, while `/ws/events` streams live events for the demo dashboard.

| Page | Main behavior |
|---|---|
| `/demo` | Configure interval, crash Node A, recover, stream log entries and recovery phases. |
| `/benchmark` | Launch small benchmark, show progress, render RTO and cost charts. |
| `/logs` | Inspect WAL records with node filter and pagination. |

The UI deliberately avoids hidden server-side state in the browser. Page load calls status/result endpoints first, then WebSocket events update the visible state.

## Reproducibility

```bash
python benchmark/benchmark_runner.py --intervals 1 2 5 10 20 30 --runs 10 --seed 42
python benchmark/chart_generator.py
python -m pytest tests/ -v
```

The report charts are regenerated from `results/summary.csv`, so the documented analysis can be reproduced after any new benchmark run.
