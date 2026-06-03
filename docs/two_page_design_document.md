# Two-Page Design Document: RTO Disaster Recovery Simulator

## 1. Purpose And Scope

This project is a simulator and benchmark tool for studying Recovery Time Objective (RTO) in a simplified distributed database environment. The main research question is how checkpoint interval affects recovery time after a database node crashes. The system models Write-Ahead Logging (WAL), checkpointing, crash injection, redo/undo recovery, two-phase commit in-doubt transactions, and a web interface for live demonstration.

The system is intentionally designed as an educational simulator, not a production database. It preserves the important recovery concepts while keeping the storage model, transaction model, and distributed coordination small enough to run locally. The final application provides three user-facing screens:

- `/demo`: interactive crash and recovery demo with live WAL and recovery events.
- `/benchmark`: benchmark dashboard for comparing RTO across checkpoint intervals.
- `/logs`: WAL inspector for checking log records by LSN and record type.

The primary users are students, reviewers, and instructors who need to observe the relationship between checkpoint frequency, WAL scan length, recovery work, and measured RTO.

## 2. System Architecture

The application is split into six major layers:

```text
Browser UI
  /demo, /benchmark, /logs
        |
        | REST API + WebSocket events
        v
FastAPI Backend
  demo router, benchmark router, logs router
        |
        v
Core Recovery Engine
  WAL, snapshot storage, checkpoint, recovery manager
        |
        v
Generated Data And Results
  WAL files, snapshot files, benchmark outputs
```

The `src/` package contains the core simulator logic. It defines binary WAL records, snapshot page read/write operations, checkpoint markers, recovery phases, crash utilities, and coordinator simulation. This layer does not depend on FastAPI or browser code, which keeps the recovery algorithm testable and reusable.

The `api/` package exposes the core logic through FastAPI. REST endpoints trigger actions such as loading a scenario, applying a custom configuration, crashing a node, recovering a node, running benchmarks, and reading WAL records. WebSocket events provide live updates to the UI, including node status changes, WAL log entries, recovery pass events, recovery record actions, coordinator queries, and benchmark progress.

The `ui/` package is a static frontend built with HTML, CSS, and vanilla JavaScript. It does not implement recovery logic. Instead, it sends control commands to the backend and renders backend state through REST responses and WebSocket events. This separation keeps the browser as a visualization layer rather than a source of truth.

The `data_gen/` package creates reproducible WAL and snapshot inputs. It supports both random custom workloads and curated demo scenarios such as clean recovery, heavy redo, global undo, in-doubt two-phase commit, and checkpoint failure.

The `benchmark/` package runs the checkpoint interval experiments, writes raw per-run results, computes aggregate statistics, and generates charts. The benchmark reuses the same recovery engine used by the live demo.

## 3. Data Model

The simulator uses two persistent data structures: a WAL file and a snapshot file.

The WAL is a fixed-size binary log. Each `LogRecord` has an increasing LSN and fields such as transaction id, record type, page id, before image, after image, redo LSN, node id, and timestamp. The supported record types are:

| Record Type | Purpose |
|---|---|
| `START` | Marks the beginning of a transaction. |
| `UPDATE` | Stores `before_image` and `after_image` for a page update. |
| `COMMIT` | Marks a transaction as committed. |
| `ABORT` | Marks a transaction as aborted. |
| `BEGIN_CHECKPOINT` | Starts a checkpoint. |
| `END_CHECKPOINT` | Completes a checkpoint and records the redo start LSN. |
| `PREPARE` | Represents a prepared transaction in two-phase commit. |
| `READY` | Represents a participant waiting for the final coordinator decision. |

The snapshot file models database pages as 64-bit integer values. A page offset is computed as:

```text
offset = page_id * 8
```

This page model is simplified, but it is enough to demonstrate redo and undo behavior:

- Redo applies the `after_image` from a committed update.
- Undo restores the `before_image` for an aborted or incomplete update.

## 4. Recovery Design

The recovery algorithm is implemented in `RecoveryManager`. It follows the terminology required by the project roadmap: Analysis, Partial Redo, and Global Undo.

The recovery flow is:

1. **Analysis**
   - Read WAL records.
   - Find the latest valid `END_CHECKPOINT`.
   - Determine `redo_lsn`.
   - Classify transactions as committed, aborted, loser, or in-doubt.

2. **Checkpoint Failure Detection**
   - Detect a `BEGIN_CHECKPOINT` without a matching later `END_CHECKPOINT`.
   - Ignore incomplete checkpoints.
   - Fall back to the previous valid checkpoint.

3. **Partial Redo**
   - Scan records from `redo_lsn`.
   - Redo `UPDATE` records belonging to committed transactions.
   - Write `after_image` values into the snapshot.

4. **Global Undo**
   - Traverse the WAL backward from the recovery range.
   - Undo updates from loser or aborted transactions.
   - Restore `before_image` values into the snapshot.

5. **In-Doubt Transaction Handling**
   - Mark `PREPARE`/`READY` transactions without `COMMIT` or `ABORT` as in-doubt.
   - Ask the coordinator simulator for a final decision when available.
   - Redo coordinator-committed transactions and undo coordinator-aborted transactions.

6. **RTO Completion**
   - Measure recovery duration.
   - Emit `rto_complete`.
   - Mark the crashed node as consistent.

This design demonstrates the trade-off between checkpoint frequency and recovery cost. A recent checkpoint reduces the WAL range that must be scanned and replayed. A long checkpoint interval increases the recovery range, which usually increases RTO.

## 5. Demo And WebSocket Event Design

The demo flow is designed for visual explanation:

1. User selects a curated scenario or clicks `Apply Config`.
2. Backend creates a new WAL/snapshot pair.
3. Backend starts a live WAL stream from the recovery-relevant checkpoint range.
4. User clicks `Crash Selected Node`.
5. Backend stops the live WAL stream and marks the node as crashed.
6. User clicks `Recover`.
7. Backend runs recovery and broadcasts recovery events to the UI.
8. UI shows redo, undo, in-doubt, coordinator, and RTO events.

The live log and recovery log are kept consistent through a shared live event history. WAL entries and recovery events are both persisted in `demo_state.live_events` and are available through `/api/demo/recent-log`. This prevents recovery events from being lost after UI refresh or WebSocket reconnect.

The live WAL stream starts from the same checkpoint range used by recovery. This avoids a confusing mismatch where the UI shows early LSNs while recovery events refer to much later LSNs. To keep the demo visually active, the stream loops over the recovery-relevant WAL tail until the user triggers a crash.

## 6. Benchmark Design

The benchmark evaluates RTO across checkpoint intervals. The independent variable is checkpoint interval, and the dependent metric is measured recovery time. The runner can execute multiple runs per interval using seeded data generation to support reproducibility.

Benchmark outputs include:

- Raw JSON per run.
- Aggregated summary CSV.
- Mean RTO.
- Median RTO.
- P99 RTO.
- Standard deviation.
- Estimated I/O, CPU, and communication cost.

The benchmark is separate from the UI demo but reuses the same WAL, snapshot, and recovery engine. This ensures that the visual demonstration and measured results are based on the same implementation.

## 7. Key Design Decisions

| Decision | Rationale |
|---|---|
| Use fixed-size binary WAL records | Makes LSN order deterministic and record parsing simple. |
| Use 64-bit integer snapshot pages | Keeps storage simple while preserving redo/undo semantics. |
| Keep recovery logic outside FastAPI | Makes the core algorithm testable and independent from UI concerns. |
| Use REST for commands and WebSocket for events | REST is clear for user actions; WebSocket is suitable for live logs and progress. |
| Provide curated scenarios | Makes video demos and grading repeatable. |
| Persist live events in backend state | Keeps WAL and recovery logs synchronized after refresh or reconnect. |
| Stream from recovery checkpoint range | Aligns visible WAL LSNs with recovery LSNs. |

## 8. Limitations

The simulator simplifies several production database concepts:

- Snapshot pages are scalar values, not real database pages.
- Checkpoint metadata is simplified and does not fully model dirty page tables or active transaction tables.
- Recovery reads WAL into memory, which is acceptable for simulator-scale workloads but not optimized for very large production logs.
- The coordinator is a simulator rather than a real distributed transaction manager.
- Cost metrics are useful for comparison and explanation, but they are not a substitute for measurements from a production distributed database.

## 9. Validation

The project includes automated tests for:

- WAL record serialization and parsing.
- Recovery redo/undo behavior.
- In-doubt transaction handling.
- Checkpoint failure detection.
- Demo API flow: config, scenario load, crash, recover.
- Live log synchronization between WAL entries and recovery events.
- Benchmark endpoint behavior.

The main verification command is:

```bash
python -m pytest
```

## 10. Conclusion

This design provides a compact but complete simulator for explaining checkpoint-based crash recovery. The core recovery engine demonstrates the essential WAL concepts, the web UI makes the process observable, and the benchmark runner quantifies how checkpoint interval affects RTO. By separating core logic, API orchestration, UI rendering, data generation, and benchmark analysis, the system remains easy to test, explain, and extend.
