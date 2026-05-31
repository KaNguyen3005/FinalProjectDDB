# Project #99 — Recovery Time Objective (RTO) Benchmark: "Disaster Recovery"
> **Category 10: Performance Benchmarking** | Distributed Database Systems (Özsu & Valduriez, 4th Ed.)

---

## 0. Project Summary

| Field | Detail |
|---|---|
| **Topic** | #99 — RTO Benchmark: Disaster Recovery |
| **Category** | 10 — Performance Benchmarking |
| **Core Question** | How does checkpoint frequency affect the recovery time of a distributed node after a crash? |
| **Primary Metric** | Recovery Time (seconds) vs. Checkpoint Interval (minutes) |
| **Statistical Output** | Mean, Median, P99 (Tail Latency) per checkpoint interval |
| **Textbook Anchor** | Özsu & Valduriez **Appendix C.6** (WAL, Checkpointing, Undo/Redo) · **§5.4.3** (Site Failure & 2PC in-doubt) · **§4.4** (Distributed Cost Model: `Cost = IO + CPU + Comm`) |
| **UI Stack** | FastAPI (Python) + WebSocket + Vanilla JS + Chart.js |

### Deliverables Summary

| # | Deliverable | Deadline |
|---|---|---|
| 1 | Project Proposal (filled template) | Week 3 |
| 2 | 2-page Design Document | Week 5 |
| 3 | GitHub repo with working code + README | Week 12 |
| 4 | Analysis report (benchmarks + textbook links) | Week 13 |
| 5 | Screen recording (3–5 min demo of **UI**) | Week 14 |
| 6 | Final exam presentation (slides) | Exam week |

---

## 1. System Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        WEB BROWSER (UI)                          │
│                                                                  │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────┐  │
│   │  Demo Dashboard │   │  Benchmark Dash │   │  Log Viewer │  │
│   │  (live nodes,   │   │  (RTO charts,   │   │  (WAL stream│  │
│   │   crash button) │   │   cost model)   │   │   UNDO/REDO)│  │
│   └────────┬────────┘   └────────┬────────┘   └──────┬──────┘  │
│            │  WebSocket (live)   │  REST (results)   │         │
└────────────┼────────────────────┼───────────────────┼──────────┘
             │                    │                   │
┌────────────▼────────────────────▼───────────────────▼──────────┐
│                    FastAPI Backend  (src/api/)                   │
│   /ws/events    /api/demo/*    /api/benchmark/*    /api/logs/*   │
└────────────┬───────────────────────────────────────────────────┘
             │  Python calls
┌────────────▼───────────────────────────────────────────────────┐
│                     Core Engine  (src/)                         │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌─────────────────┐  │
│  │  node/   │ │  log/    │ │ recovery/  │ │  benchmark/     │  │
│  │ (3 procs)│ │(WAL+2PC) │ │(Özsu C.6)  │ │  (runner+stats) │  │
│  └──────────┘ └──────────┘ └────────────┘ └─────────────────┘  │
└────────────────────────────────────────────────────────────────┘
             │
┌────────────▼───────────────────────────────────────────────────┐
│                       data/                                     │
│   transaction_log.bin (~1 GB)    db_snapshot.bin (~500 MB)      │
└────────────────────────────────────────────────────────────────┘
```

### Communication Protocol

| Channel | Protocol | Purpose |
|---|---|---|
| UI ↔ Backend (live events) | **WebSocket** `/ws/events` | Stream node status, log entries, RTO timer tick, crash events in real-time |
| UI ↔ Backend (control) | **REST POST** | Trigger crash, set checkpoint interval, start benchmark run |
| UI ↔ Backend (results) | **REST GET** | Fetch benchmark summary CSV, chart data JSON |
| Backend ↔ Nodes | Python `multiprocessing` Pipes/Queues | Inter-process communication for 3 simulated nodes |

---

## 2. UI Design — Screens & Interactions

### Screen 1: Demo Dashboard (`/demo`)

**Purpose**: Live visual demonstration for the screen recording. Shows the 3-node cluster in real-time, allows one-click crash injection, and displays the RTO timer.

```
┌──────────────────────────────────────────────────────────────────────┐
│  💾 RTO Disaster Recovery Demo          [Checkpoint: 5 min ▼]  ⚙️  │
├──────────────────┬───────────────────────────────────────────────────┤
│                  │                                                    │
│   CLUSTER MAP    │              LIVE LOG STREAM                       │
│                  │  ┌────────────────────────────────────────────┐   │
│  ┌──────────┐    │  │ [12:04:01] LSN=4821 TXN#302 COMMIT        │   │
│  │  NODE A  │    │  │ [12:04:01] LSN=4822 TXN#303 START         │   │
│  │ PRIMARY  │    │  │ [12:04:02] LSN=4823 TXN#303 UPDATE p=17   │   │
│  │ ● RUNNING│    │  │ [12:04:02] ★ CHECKPOINT written (LSN=4823)│   │
│  │          │    │  │ [12:04:03] LSN=4824 TXN#304 START         │   │
│  │ txn: 304 │    │  │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │   │
│  │ lsn: 4824│    │  └────────────────────────────────────────────┘   │
│  └────┬─────┘    │                                                    │
│       │WAL       │              RECOVERY TIMELINE                     │
│  ┌────▼─────┐    │  ┌────────────────────────────────────────────┐   │
│  │  NODE B  │    │  │  t=0s  💥 CRASH INJECTED                   │   │
│  │ REPLICA  │    │  │  t=1s  📖 Analysis (scan from END_CKPT)    │   │
│  │ ● RUNNING│    │  │  t=2s  ⚠️  TXN#305 IN-DOUBT (PREPARE)     │   │
│  └──────────┘    │  │  t=3s  ↩️  Partial Redo (after_image ×4)  │   │
│  ┌──────────┐    │  │  t=5s  ↪️  Global Undo (before_image ×2)  │   │
│  │  NODE C  │    │  │  t=6s  ✅ CONSISTENT — RTO = 6.23s         │   │
│  │ REPLICA  │    │  └────────────────────────────────────────────┘   │
│  │ ● RUNNING│    │                                                    │
│  └──────────┘    │  ┌─────────────────────────────────────────────┐  │
│                  │  │  RTO STOPWATCH        ⏱  00:00:06.23        │  │
│                  │  └─────────────────────────────────────────────┘  │
│  [💥 CRASH A]   │                                                    │
│  [▶ RECOVER]    │                                                    │
│  [⏸ PAUSE TXN] │                                                    │
└──────────────────┴───────────────────────────────────────────────────┘
```

**Node states & colors**:
- `● RUNNING` — green pulse animation
- `💥 CRASHED` — red, static, blinking icon
- `🔄 RECOVERING` — amber, spinning indicator
- `✅ CONSISTENT` — bright green, checkmark

**Interactions**:
- **[💥 CRASH NODE A]**: POST `/api/demo/crash` → backend kills Node A process → WebSocket pushes crash event → UI transitions node to CRASHED state, starts RTO stopwatch.
- **[▶ RECOVER]**: POST `/api/demo/recover` → starts Recovery Manager → WebSocket streams each pass (Analysis / REDO / UNDO) as log lines → stopwatch stops on CONSISTENT event.
- **Checkpoint interval dropdown**: Changes the interval for the *next* run so students can show "1 min vs 10 min" live.
- **Live Log Stream**: Auto-scrolling `<pre>` panel, color-coded by record type: START=gray, UPDATE=blue, COMMIT=green, ABORT=red, PREPARE=orange, READY=yellow, BEGIN_CHECKPOINT / END_CHECKPOINT=yellow star (two entries per checkpoint cycle, per Özsu Appendix C.6).

---

### Screen 2: Benchmark Dashboard (`/benchmark`)

**Purpose**: Show the full statistical analysis. This is what the analysis report is built from.

```
┌──────────────────────────────────────────────────────────────────────┐
│  📊 RTO Benchmark Results                    [▶ Run New Benchmark]  │
├────────────────────────────────┬─────────────────────────────────────┤
│                                │                                      │
│   RTO vs CHECKPOINT INTERVAL   │      COST MODEL BREAKDOWN            │
│                                │                                      │
│  sec                           │  Cost                                │
│  120 ┤          ·········· P99 │  units  ██ IO  ░░ CPU  ▓▓ Comm      │
│   90 ┤      ·····             │         ████████████████████         │
│   60 ┤  ····    ─────── Mean  │         ████████░░░░░░▓▓▓▓▓▓         │
│   30 ┤──        - - - Median  │         ████░░░░░░░░░░▓▓▓▓▓▓▓▓       │
│    0 └─┬──┬──┬───┬───┬───┬─  │         1   2   5  10  20  30 min    │
│        1  2  5  10  20  30    │                                      │
│             min               │                                      │
├────────────────────────────────┴─────────────────────────────────────┤
│                                                                        │
│   RTO VARIANCE HEATMAP (runs × interval)                              │
│                                                                        │
│        1min  2min  5min  10min  20min  30min                          │
│  run1  ████  ████  ████  ████   ████   ████   (color = RTO duration)  │
│  run2  ████  ████  ████  ████   ████   ████                           │
│   ...                                                                  │
│  run10 ████  ████  ████  ████   ████   ████                           │
│                                                                        │
├────────────────────────────────────────────────────────────────────────┤
│  STATISTICS TABLE                                                      │
│  Interval │ Mean(s) │ Median(s) │ P99(s) │ Std Dev │ IO Cost │ Theory │
│  1 min    │   5.2   │   5.1     │   6.8  │  0.4    │  312    │  5.0s  │
│  5 min    │  18.4   │  17.9     │  24.1  │  1.8    │ 1560    │ 18.1s  │
│  10 min   │  34.7   │  33.2     │  48.9  │  3.6    │ 3120    │ 34.5s  │
│  30 min   │  98.2   │  94.1     │ 119.4  │  9.1    │ 9360    │ 96.8s  │
└────────────────────────────────────────────────────────────────────────┘
```

**Interactions**:
- **[▶ Run New Benchmark]**: Opens a modal to configure (interval list, number of runs, seed) → POST `/api/benchmark/run` → progress bar streams via WebSocket → charts auto-update as each run completes.
- **Charts**: Interactive (hover tooltip shows exact value). Built with Chart.js.
- **Statistics Table**: Sortable columns, exportable to CSV via button.
- **Theory column**: Shows the theoretical RTO predicted by the Özsu cost model formula alongside the empirical result.

---

### Screen 3: Log Inspector (`/logs`)

**Purpose**: Deep-dive tool for the design document and report. Shows the full WAL structure including 2PC records and checkpoint markers as defined in Özsu Appendix C.6 and §5.4.3.

```
┌──────────────────────────────────────────────────────────────────────┐
│  📋 WAL Log Inspector              [Node: A ▼]  [Filter: ALL ▼]     │
├──────────────────────────────────────────────────────────────────────┤
│  LSN   │ TXN_ID │ Type              │ Page │ Before   │ After        │
├──────────────────────────────────────────────────────────────────────┤
│  4819  │  301   │ ⭐ BEGIN_CKPT     │  -   │ —        │ —            │
│  4820  │  301   │ ⭐ END_CKPT       │  -   │ —        │ redo_lsn=4819│
│  4821  │  302   │ 🔵 START          │  -   │ —        │ —            │
│  4822  │  302   │ 🔵 UPDATE         │  17  │ $1000    │ $1200        │
│  4823  │  302   │ ✅ COMMIT         │  -   │ —        │ —            │
│  4824  │  303   │ 🔵 START          │  -   │ —        │ —            │
│  4825  │  303   │ 🔵 UPDATE         │  22  │ $500     │ $450         │
│  4826  │  305   │ 🟠 PREPARE        │  -   │ —        │ coordinator? │
│  💥 ── CRASH at LSN 4826 ─────────────────────────────────────────  │
│  ── RECOVERY MANAGER (Özsu Appendix C.6) ─────────────────────────  │
│  4827  │  302   │ ↩️  PARTIAL REDO  │  17  │ —        │ apply $1200  │
│  4828  │  303   │ ↪️  GLOBAL UNDO   │  22  │ restore  │ $500         │
│  ⚠️  305  │  IN-DOUBT: PREPARE found, no COMMIT/ABORT (§5.4.3)       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

### Backend (Python)

| Component | Library/Tool | Purpose |
|---|---|---|
| API server | `FastAPI` | REST endpoints + WebSocket server |
| WebSocket | `fastapi.websockets` | Push real-time events to browser |
| Node simulation | `multiprocessing` | 3 independent OS processes = 3 DB nodes |
| Log storage | `struct` (binary) | Pack/unpack `LogRecord` to `.bin` file |
| Stats | `numpy`, `scipy` | Mean, Median, P99 calculation |
| Data generation | `faker`, `random` | Synthetic transaction workload |
| Crash injection | `os.kill(pid, SIGKILL)` | Hard crash simulation |
| Server | `uvicorn` | ASGI server for FastAPI |

### Frontend (Browser)

| Component | Library/Tool | Purpose |
|---|---|---|
| Charts | `Chart.js 4.x` (CDN) | Line chart, bar chart, heatmap |
| WebSocket client | Native browser `WebSocket` API | Receive live events from backend |
| Styling | Custom CSS + CSS Variables | Dark terminal aesthetic |
| Fonts | `JetBrains Mono` (monospace) + `Syne` (display) | Tech/systems feel |
| Build system | **None** | Pure HTML + JS in `ui/` folder, served by FastAPI static files |

> **No Node.js / npm build step required.** The entire frontend is plain HTML/CSS/JS files served as static assets by FastAPI. This keeps setup simple and avoids frontend toolchain issues.

---

## 4. Updated Directory Structure

```
project-99-rto-benchmark/
│
├── README.md                          # Setup instructions + screenshots
├── requirements.txt                   # All Python dependencies
├── .gitignore
├── run.py                             # ONE command to start everything: uvicorn + open browser
│
├── src/                               # Core engine (no UI dependency)
│   ├── __init__.py
│   ├── main.py                        # CLI entry point (--generate, --crash-and-recover, --benchmark)
│   │
│   ├── node/
│   │   ├── node.py                    # Node process: handles transactions, writes WAL
│   │   ├── buffer_pool.py             # In-memory page cache (dirty page tracking)
│   │   └── storage_engine.py         # Reads/writes db_snapshot.bin
│   │
│   ├── log/
│   │   ├── log_record.py             # LogRecord dataclass + binary serialization
│   │   ├── log_writer.py             # Appends records to transaction_log.bin
│   │   └── log_reader.py             # Sequential log scanning
│   │
│   ├── checkpoint/
│   │   └── checkpoint_manager.py     # Triggers checkpoint every N seconds; writes CHECKPOINT LSN
│   │
│   ├── recovery/
│   │   ├── recovery_manager.py       # Partial Redo + Global Undo (Özsu C.6); in-doubt handling (§5.4.3)
│   │   ├── transaction_table.py      # Active transaction tracking
│   │   └── dirty_page_table.py       # Dirty page tracking
│   │
│   ├── crash/
│   │   ├── crash_injector.py         # os.kill(pid, SIGKILL) at deterministic point
│   │   └── recovery_timer.py         # Records t_crash → t_consistent = RTO
│   │
│   ├── coordinator/
│   │   └── coordinator.py            # Manages 3 nodes, global checkpoint signals, 2PC
│   │
│   └── integrity/
│       └── integrity_checker.py      # SHA-256 verify: recovered state == expected committed state
│
├── benchmark/
│   ├── benchmark_runner.py           # Loop: intervals × runs → collect RTO
│   ├── stats_analyzer.py             # Mean, Median, P99, Std Dev from raw results
│   └── cost_model.py                 # Özsu Cost = IO + CPU + Comm formula
│
├── data_gen/
│   ├── generate_logs.py              # Generates 1 GB transaction_log.bin
│   └── generate_snapshot.py          # Generates 500 MB db_snapshot.bin
│
├── api/                               # FastAPI application
│   ├── __init__.py
│   ├── app.py                         # FastAPI app instance, static file mount, CORS
│   ├── routers/
│   │   ├── demo.py                    # POST /api/demo/crash, /api/demo/recover, /api/demo/status
│   │   ├── benchmark.py               # POST /api/benchmark/run, GET /api/benchmark/results
│   │   └── logs.py                    # GET /api/logs/stream, GET /api/logs/records
│   └── websocket/
│       ├── manager.py                 # ConnectionManager: broadcast events to all WS clients
│       └── events.py                  # Event schema: NodeStatusEvent, LogEvent, RTOEvent, BenchmarkProgressEvent
│
├── ui/                                # Frontend (served as static files by FastAPI)
│   ├── index.html                     # Root: redirects to /demo
│   ├── demo.html                      # Screen 1: Live Demo Dashboard
│   ├── benchmark.html                 # Screen 2: Benchmark Dashboard
│   ├── logs.html                      # Screen 3: Log Inspector
│   │
│   ├── css/
│   │   ├── base.css                   # CSS variables, reset, typography (JetBrains Mono + Syne)
│   │   ├── demo.css                   # Node cards, log stream, RTO stopwatch styles
│   │   ├── benchmark.css              # Chart containers, stats table styles
│   │   └── logs.css                   # Log table, UNDO/REDO highlight styles
│   │
│   └── js/
│       ├── ws-client.js               # WebSocket client: connects, dispatches events by type
│       ├── demo.js                    # Demo page logic: node state machine, log stream, stopwatch
│       ├── benchmark.js               # Benchmark page: fetch results, render Chart.js charts
│       └── logs.js                    # Log inspector: fetch + filter log records
│
├── results/
│   ├── raw/                           # Per-run JSON: rto_interval_5min_run_3.json
│   ├── summary.csv                    # Aggregated: interval, mean, median, p99, std, io_cost
│   └── charts/                        # Pre-generated PNG charts (for report/slides)
│       ├── rto_vs_interval.png
│       ├── cost_breakdown.png
│       └── rto_heatmap.png
│
├── data/                              # Generated datasets (git-ignored, large files)
│   ├── transaction_log.bin            # ~1 GB WAL log
│   └── db_snapshot.bin               # ~500 MB snapshot
│
├── tests/
│   ├── test_log_record.py
│   ├── test_recovery_manager.py      # UNDO/REDO correctness
│   ├── test_api_demo.py              # FastAPI TestClient for /api/demo/*
│   └── test_benchmark_runner.py
│
└── docs/
    ├── design_document.md            # 2-page: architecture, Özsu C.6 recovery flow, in-doubt handling §5.4.3
    ├── analysis_report.md            # Benchmark results + §4.4 cost model derivation
    └── diagrams/
        ├── architecture.png
        ├── ozsu_recovery_flow.png     # Partial Redo / Global Undo / BEGIN+END_CHECKPOINT flow
        └── ui_screens.png
```

---

## 5. Milestones

### Milestone 1 — Core Engine + Data Generation (Week 5)

**Goal**: The simulation runs headlessly (no UI). Data on disk. Crash-and-recover cycle works.

Tasks:
- [ ] `data_gen/generate_logs.py` → 1 GB `transaction_log.bin` (`--seed 42`)
- [ ] `data_gen/generate_snapshot.py` → 500 MB `db_snapshot.bin`
- [ ] `src/log/log_record.py` → `LogRecord` dataclass + binary `struct` pack/unpack. Record types MUST follow Özsu **Appendix C.6** + **§5.4.3**:
  ```python
  class RecordType(IntEnum):
      # Standard WAL records (Appendix C.6)
      START            = 0   # transaction begins
      UPDATE           = 1   # carries before_image + after_image (Özsu C.6)
      COMMIT           = 2
      ABORT            = 3
      # Checkpoint records — Özsu C.6 requires TWO markers:
      BEGIN_CHECKPOINT = 4   # written when checkpoint starts
      END_CHECKPOINT   = 5   # written after all dirty pages flushed; anchors the redo_lsn
      # 2PC records — required for distributed recovery (Özsu §5.4.3):
      PREPARE          = 6   # coordinator sent PREPARE; participant logged vote
      READY            = 7   # participant voted YES (ready to commit)
      # COMMIT/ABORT (types 2/3) reused for coordinator's final decision
  ```
  > **Why 2PC records matter**: after a crash, if Recovery Manager finds a `PREPARE` with no subsequent `COMMIT` or `ABORT`, that transaction is **in-doubt** (§5.4.3). It cannot be unilaterally UNDO'd — the coordinator must be contacted first. This must be flagged in the recovery log and shown in the UI.
- [ ] `src/node/node.py` → runs as `multiprocessing.Process`, writes WAL with all record types above
- [ ] `src/checkpoint/checkpoint_manager.py` → fires every N seconds; writes `BEGIN_CHECKPOINT` first, flushes dirty pages, then writes `END_CHECKPOINT` with the LSN anchor (Özsu Appendix C.6 two-marker protocol)
- [ ] `src/crash/crash_injector.py` + `recovery_timer.py` → kill + measure RTO
- [ ] `src/recovery/recovery_manager.py` → implement recovery using Özsu's framework (Appendix C.6): scan log from last `END_CHECKPOINT`, apply **Partial Redo** (re-apply `after_image` for committed txns to enforce Durability), then **Global Undo** (restore `before_image` for incomplete txns). Map to ARIES passes internally but use Özsu terminology in all documentation and comments.
- [ ] `src/integrity/integrity_checker.py` → SHA-256 verify
- [ ] `python src/main.py --crash-and-recover --interval 5` prints RTO to stdout

---

### Milestone 2 — Benchmark Suite (Week 8)

**Goal**: Full benchmark matrix runs automatically. `results/summary.csv` is populated.

Tasks:
- [ ] `benchmark/benchmark_runner.py` → loop `[1, 2, 5, 10, 20, 30]` min × 10 runs each
- [ ] `benchmark/stats_analyzer.py` → reads `results/raw/*.json` → computes Mean/Median/P99/Std
- [ ] `benchmark/cost_model.py` → implements `Cost = C_io*#IO + C_cpu*#cpu + C_msg*#msg + C_tr*#bytes`
- [ ] `results/summary.csv` → columns: `interval_min, mean_s, median_s, p99_s, std_s, io_cost, cpu_cost, comm_cost, theory_rto_s`
- [ ] `python benchmark/benchmark_runner.py` runs unattended in ~30 minutes

---

### Milestone 3 — FastAPI Backend + WebSocket (Week 10)

**Goal**: The API is running. All engine actions are triggerable via HTTP. WebSocket pushes events.

Tasks:
- [ ] `api/app.py` → FastAPI app, mount `ui/` as static files at `/`
- [ ] `api/websocket/manager.py` → `ConnectionManager` with `broadcast(event_dict)`
- [ ] `api/websocket/events.py` → event schemas:
  ```python
  # Examples of events pushed via WebSocket:
  {"type": "node_status",   "node": "A", "status": "RUNNING",    "txn": 304, "lsn": 4824}
  {"type": "log_entry",     "lsn": 4824, "txn_id": 304, "record_type": "UPDATE", ...}
  {"type": "log_entry",     "lsn": 4825, "txn_id": 305, "record_type": "PREPARE", ...}
  {"type": "crash",         "node": "A", "timestamp": 1234567890.0}
  {"type": "recovery_pass", "pass": "ANALYSIS",    "progress": 0.45}
  {"type": "recovery_pass", "pass": "PARTIAL_REDO","txns_redone": 4}   # Özsu C.6 term
  {"type": "recovery_pass", "pass": "GLOBAL_UNDO", "txns_undone": 2}   # Özsu C.6 term
  {"type": "in_doubt_txn",  "txn_id": 305, "message": "awaiting coordinator — §5.4.3"}
  {"type": "rto_complete",  "rto_seconds": 6.23, "consistent": true}
  {"type": "benchmark_progress", "interval": 5, "run": 3, "rto": 18.4, "total_runs": 10}
  ```
- [ ] `api/routers/demo.py`:
  - `POST /api/demo/crash` → crash Node A → start broadcasting events
  - `POST /api/demo/recover` → start Recovery Manager → broadcast pass events
  - `POST /api/demo/config` → set checkpoint interval, reset state
  - `GET /api/demo/status` → current node statuses (for page load)
- [ ] `api/routers/benchmark.py`:
  - `POST /api/benchmark/run` → run benchmark in background thread → stream progress via WS
  - `GET /api/benchmark/results` → return `results/summary.csv` as JSON
  - `GET /api/benchmark/raw/{interval}` → raw per-run results for a specific interval
- [ ] `api/routers/logs.py`:
  - `GET /api/logs/records?node=A&offset=0&limit=100` → paginated log records
  - `GET /api/logs/stream` → Server-Sent Events stream of new log entries (for live log panel)

---

### Milestone 4 — Frontend UI (Week 11–12)

**Goal**: All 3 screens are functional and visually polished. Ready for screen recording.

#### Aesthetic Direction: Dark Terminal / Systems Monitoring

- **Background**: `#0a0c10` (near-black) with subtle scanline texture
- **Accent**: `#00ff88` (terminal green) for healthy/running states; `#ff3b3b` for crash; `#ffaa00` for recovery
- **Font**: `JetBrains Mono` for all log data and metrics; `Syne` for headings
- **Node cards**: Bordered panels with animated pulse rings for RUNNING state, flicker on CRASH
- **Charts**: Dark background, colored lines with glow effect; gridlines in `rgba(255,255,255,0.05)`

#### `ui/js/ws-client.js`
```javascript
// Singleton WebSocket connection, dispatches events by type
const WS_URL = `ws://${location.host}/ws/events`;
const handlers = {};

export function on(eventType, fn) { handlers[eventType] = fn; }

export function connect() {
  const ws = new WebSocket(WS_URL);
  ws.onmessage = ({ data }) => {
    const event = JSON.parse(data);
    if (handlers[event.type]) handlers[event.type](event);
  };
  ws.onclose = () => setTimeout(connect, 2000); // auto-reconnect
}
```

#### `ui/js/demo.js` key logic
```javascript
import { on, connect } from './ws-client.js';

// Node state machine
on('node_status',   e => updateNodeCard(e.node, e.status, e.txn, e.lsn));
on('log_entry',     e => appendLogLine(e));
on('crash',         e => { setNodeCrashed('A'); startStopwatch(); });
on('recovery_pass', e => appendRecoveryTimeline(e));
on('rto_complete',  e => { stopStopwatch(e.rto_seconds); setNodeConsistent('A'); });

document.getElementById('btn-crash').onclick = () =>
  fetch('/api/demo/crash', { method: 'POST' });

document.getElementById('btn-recover').onclick = () =>
  fetch('/api/demo/recover', { method: 'POST' });
```

#### `ui/js/benchmark.js` key logic
```javascript
// Fetch summary and render all 3 charts on page load
async function loadResults() {
  const res  = await fetch('/api/benchmark/results');
  const data = await res.json(); // [{interval, mean, median, p99, std, io_cost, ...}, ...]
  renderLineChart(data);         // RTO vs Interval (Mean/Median/P99)
  renderBarChart(data);          // Stacked: IO / CPU / Comm cost
  renderHeatmap(data);           // Heatmap: run index × interval → RTO color
  renderStatsTable(data);        // Sortable HTML table
}

// Live update during a benchmark run
on('benchmark_progress', e => {
  updateProgressBar(e.interval, e.run, e.total_runs);
  updateLineChartPartial(e);     // add dot as each run completes
});
```

#### `ui/css/base.css` CSS Variables
```css
:root {
  --bg-primary:    #0a0c10;
  --bg-card:       #111318;
  --bg-card-hover: #161a22;
  --border:        #1e2330;
  --accent-green:  #00ff88;
  --accent-red:    #ff3b3b;
  --accent-amber:  #ffaa00;
  --accent-blue:   #4da6ff;
  --text-primary:  #e8eaf0;
  --text-muted:    #5a6070;
  --font-mono:     'JetBrains Mono', monospace;
  --font-display:  'Syne', sans-serif;
  --glow-green:    0 0 12px rgba(0, 255, 136, 0.4);
  --glow-red:      0 0 12px rgba(255, 59, 59, 0.5);
}
```

#### `run.py` — One-Command Startup
```python
# run.py — start everything with: python run.py
import subprocess, webbrowser, time, sys

def main():
    print("🚀 Starting RTO Benchmark Dashboard...")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.app:app",
                               "--host", "0.0.0.0", "--port", "8000", "--reload"])
    time.sleep(1.5)
    webbrowser.open("http://localhost:8000/demo")
    print("✅ Open: http://localhost:8000")
    print("   Demo:      http://localhost:8000/demo")
    print("   Benchmark: http://localhost:8000/benchmark")
    print("   Logs:      http://localhost:8000/logs")
    try:
        server.wait()
    except KeyboardInterrupt:
        server.terminate()

if __name__ == "__main__":
    main()
```

---

### Milestone 5 — Documentation, Report & Demo (Week 13–14)

- [ ] **Design Document** (2 pages, `docs/design_document.md`): architecture diagram, recovery flow mapped to Özsu Appendix C.6 (Partial Redo / Global Undo / BEGIN+END_CHECKPOINT) and §5.4.3 (in-doubt transactions), crash injection methodology, variable-control table, UI architecture overview.
- [ ] **Analysis Report** (`docs/analysis_report.md`): benchmark results tables + all 3 charts embedded + Özsu cost model derivation with empirical validation + conclusion.
- [ ] **Screen Recording** (3–5 min): Open demo page → show live log streaming (including PREPARE records) → click CRASH NODE A → show RTO stopwatch → click RECOVER → watch Analysis / Partial Redo / Global Undo stream in, with in-doubt banner if applicable → RTO displayed → switch to Benchmark dashboard → show all charts. **The UI makes this effortless to film.**
- [ ] **Presentation Slides**: Pull key chart (RTO vs Interval line chart) + architecture diagram + cost formula + conclusion.

---

## 6. Grading Checklist (Category 10 — Excellent Tier)

| Criterion | Requirement | How Achieved |
|---|---|---|
| **Methodology** | Strict variable control; ≥ multiple runs | `benchmark_runner.py`: fixed seed, ≥10 runs/interval, `--seed` arg |
| **Visual Analysis** | Professional charts, labeled axes | Chart.js in `benchmark.html` (interactive) + PNG export for report |
| **Statistical Rigor** | Mean, Median, **P99** reported | `stats_analyzer.py`; P99 shown as separate line on chart |
| **Textbook Link** | Relate to Özsu `Cost = IO + CPU + Comm` | `cost_model.py` cites **§4.4**; Design Doc maps recovery steps to **Appendix C.6** (Partial Redo / Global Undo / BEGIN+END_CHECKPOINT); Report cites **§5.4.3** for in-doubt transaction handling |

---

## 7. Key Code References

### `src/recovery/recovery_manager.py` — Özsu-Aligned Recovery (Appendix C.6 + §5.4.3)

The implementation uses ARIES internally for efficiency, but every step is mapped to Özsu's terminology in comments so the Design Document and Analysis Report can cite the textbook directly.

```python
class RecoveryManager:
    """
    Implements recovery per Özsu & Valduriez Appendix C.6 (WAL-based recovery)
    and §5.4.3 (handling site failures in distributed transactions).

    Internal 3-pass structure maps to Özsu as follows:
      Pass 1 (Analysis)  → locate last END_CHECKPOINT LSN; build transaction state table
      Pass 2 (Redo)      → "Partial Redo": re-apply after_image for committed txns → Durability
      Pass 3 (Undo)      → "Global Undo": restore before_image for LOSER txns → Atomicity
    """

    def recover(self, log_path: str, snapshot_path: str,
                event_cb=None) -> float:
        """Returns RTO in seconds. event_cb(event_dict) streams events to UI."""
        t0 = time.perf_counter()

        # --- Pass 1: Analysis --- (Özsu C.6: scan from END_CHECKPOINT)
        redo_lsn, txn_table = self._analysis_pass(log_path, event_cb)
        # txn_table maps txn_id → state: COMMITTED | ABORTED | IN_DOUBT | LOSER
        # IN_DOUBT = found PREPARE but no COMMIT/ABORT → §5.4.3 in-doubt handling

        # --- Pass 2: Partial Redo --- (Özsu C.6: enforce Durability)
        # Re-apply after_image for all COMMITTED transactions since redo_lsn
        self._partial_redo(log_path, redo_lsn, txn_table, event_cb)

        # --- Pass 3: Global Undo --- (Özsu C.6: enforce Atomicity)
        # Restore before_image for all LOSER (incomplete) transactions
        losers = {t for t, s in txn_table.items() if s == "LOSER"}
        self._global_undo(log_path, losers, event_cb)

        # --- Handle IN_DOUBT transactions --- (Özsu §5.4.3)
        in_doubt = {t for t, s in txn_table.items() if s == "IN_DOUBT"}
        if in_doubt:
            self._handle_in_doubt(in_doubt, event_cb)
            # Cannot UNDO unilaterally — must query coordinator for final decision

        return time.perf_counter() - t0

    def _handle_in_doubt(self, txn_ids: set, event_cb):
        """
        Özsu §5.4.3: A transaction is in-doubt if PREPARE was logged but
        no COMMIT or ABORT was found. The recovering node must contact the
        coordinator (or surviving replicas) to determine the outcome.
        Until resolved, these transactions hold their locks.
        """
        for txn_id in txn_ids:
            if event_cb:
                event_cb({"type": "in_doubt_txn", "txn_id": txn_id,
                          "message": f"TXN#{txn_id} in-doubt: awaiting coordinator decision"})
```

### `benchmark/cost_model.py` — Özsu Formula
```python
def estimate_recovery_cost(interval_min: int, txn_rate: float,
                            C_io=1.0, C_cpu=0.01, C_msg=5.0, C_tr=0.0001,
                            avg_record_bytes=200, page_size=4096) -> dict:
    """
    Distributed cost model from Özsu & Valduriez §4.4:
      Total_Cost = C_io * #IO + C_cpu * #instructions + C_msg * #messages + C_tr * #bytes

    Applied to recovery:
      #IO   = log pages to read since last END_CHECKPOINT  (grows with interval)
      #cpu  = Partial Redo + Global Undo operations
      #msg  = 2PC coordinator messages to resolve in-doubt transactions (§5.4.3)
      #bytes = data exchanged to verify replica consistency
    """
    log_bytes = interval_min * 60 * txn_rate * avg_record_bytes
    num_io    = log_bytes / page_size
    num_cpu   = log_bytes / 50
    num_msg   = 4          # fixed: coordinator verifies consistency with 2 replicas (2×2PC msgs)
    num_bytes = 1024       # consistency probe size

    return {
        "io":    C_io  * num_io,
        "cpu":   C_cpu * num_cpu,
        "comm":  C_msg * num_msg + C_tr * num_bytes,
        "total": C_io  * num_io + C_cpu * num_cpu + C_msg * num_msg + C_tr * num_bytes,
        # Theoretical RTO (seconds): assume 10ms per IO operation
        "theory_rto_s": num_io * 0.010
    }
```

---

## 8. Quick-Start Commands

```bash
# 1. Install Python dependencies
pip install -r requirements.txt
# requirements: fastapi uvicorn numpy scipy faker

# 2. Generate datasets (one-time, creates ~1.5 GB in data/)
python data_gen/generate_logs.py     --transactions 5000000 --seed 42
python data_gen/generate_snapshot.py --pages 125000 --seed 42

# 3. Start the full application (backend + UI)
python run.py
# → Browser opens at http://localhost:8000/demo automatically

# 4. (Optional) Run benchmark headlessly without UI
python benchmark/benchmark_runner.py --intervals 1 2 5 10 20 30 --runs 10 --seed 42

# 5. Run tests
pytest tests/ -v
```

---

## 9. References

| Source | Relevant Sections |
|---|---|
| Özsu & Valduriez, *Principles of Distributed Database Systems*, 4th Ed. | **Appendix C.6** — DBMS Reliability: WAL, before/after images, Checkpoint (BEGIN+END), Partial Redo, Global Undo |
| Özsu & Valduriez, *Principles of Distributed Database Systems*, 4th Ed. | **§5.4.3** — Dealing with Site Failures: in-doubt transactions, 2PC log records (PREPARE/READY/COMMIT/ABORT), coordinator recovery |
| Özsu & Valduriez, *Principles of Distributed Database Systems*, 4th Ed. | **§4.4** — Distributed Cost Model: `Cost = C_io·#IO + C_cpu·#cpu + C_msg·#msg + C_tr·#bytes` |
| ARIES Algorithm | Mohan et al., 1992 — referenced as implementation basis; mapped to Özsu's Partial Redo / Global Undo framework in all documentation |
| FastAPI Documentation | WebSocket support, static file serving, background tasks |
| Chart.js Documentation | Line chart with multiple datasets, stacked bar, heatmap via matrix plugin |
| JetBrains Mono Font | https://fonts.google.com/specimen/JetBrains+Mono |
