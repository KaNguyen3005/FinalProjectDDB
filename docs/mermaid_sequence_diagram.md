# Mermaid Sequence Diagrams

Tài liệu này mô tả các luồng runtime chính của project hiện tại bằng Mermaid sequence diagram.

## 1. Demo Flow: Apply Config, Live Log, Crash, Recover

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant DemoUI as Browser UI /demo
    participant WS as WebSocket /ws/events
    participant DemoAPI as FastAPI Demo Router
    participant State as DemoState
    participant DataGen as data_gen
    participant WAL as WAL File
    participant Snapshot as Snapshot File
    participant Recovery as RecoveryManager
    participant Coord as CoordinatorSimulator

    User->>DemoUI: Click Apply Config
    DemoUI->>DemoAPI: POST /api/demo/config
    DemoAPI->>State: Create new run_id, log_path, snapshot_path
    DemoAPI->>DataGen: generate_logs(transactions, checkpoint_every, pages, seed)
    DataGen->>Snapshot: Create snapshot pages
    DataGen->>WAL: Append BEGIN_CHECKPOINT / END_CHECKPOINT
    loop For each generated transaction
        DataGen->>WAL: Append START / UPDATE / COMMIT|ABORT|PREPARE|READY
        opt checkpoint interval reached
            DataGen->>WAL: Append BEGIN_CHECKPOINT / END_CHECKPOINT
        end
    end
    DemoAPI->>State: Refresh current_txn/current_lsn
    DemoAPI-->>DemoUI: Return demo status
    DemoAPI->>WS: Broadcast demo_log_stream_state(running=true)

    par Live WAL stream
        loop Until crash
            DemoAPI->>WAL: Read recovery-relevant WAL tail
            DemoAPI->>WS: Broadcast log_entry
            WS-->>DemoUI: Render Live Log row
            opt custom config keeps running
                DemoAPI->>WAL: Append new live transaction with new LSN
                DemoAPI->>Snapshot: Apply live page update
                opt live checkpoint interval reached
                    DemoAPI->>WAL: Append BEGIN_CHECKPOINT / END_CHECKPOINT
                end
            end
        end
    end

    User->>DemoUI: Click Crash Selected Node
    DemoUI->>DemoAPI: POST /api/demo/crash
    DemoAPI->>State: Cancel log stream task, mark node CRASHED
    DemoAPI->>WS: Broadcast crash event
    WS-->>DemoUI: Start RTO stopwatch
    DemoAPI->>WS: Broadcast node_status(CRASHED)
    WS-->>DemoUI: Update node card

    User->>DemoUI: Click Recover
    DemoUI->>DemoAPI: POST /api/demo/recover
    DemoAPI->>State: Mark node RECOVERING
    DemoAPI->>WS: Broadcast node_status(RECOVERING)
    DemoAPI->>Recovery: recover(log_path, snapshot_path, event_cb, coordinator.resolve)
    Recovery->>WAL: Read all WAL records
    Recovery-->>DemoAPI: Emit recovery_pass(ANALYSIS)
    Recovery->>Recovery: Find latest valid END_CHECKPOINT and redo_lsn
    Recovery->>Recovery: Classify COMMITTED / ABORTED / LOSER / IN_DOUBT
    Recovery-->>DemoAPI: Emit recovery_pass(ANALYSIS complete)

    opt Incomplete checkpoint detected
        Recovery-->>DemoAPI: Emit checkpoint_failure
    end

    loop Partial Redo
        Recovery->>Snapshot: Write after_image for committed UPDATE
        Recovery-->>DemoAPI: Emit recovery_record(REDO)
    end

    loop Global Undo
        Recovery->>Snapshot: Write before_image for loser/aborted UPDATE
        Recovery-->>DemoAPI: Emit recovery_record(UNDO)
    end

    loop In-doubt transaction
        Recovery-->>DemoAPI: Emit in_doubt_txn
        Recovery->>Coord: resolve(txn_id)
        Coord-->>Recovery: COMMIT / ABORT / UNKNOWN
        Recovery-->>DemoAPI: Emit coordinator_query / coordinator_decision
        opt coordinator decision is COMMIT
            Recovery->>Snapshot: REDO prepared updates
            Recovery-->>DemoAPI: Emit recovery_record(COORDINATOR_REDO)
        end
        opt coordinator decision is ABORT
            Recovery->>Snapshot: UNDO prepared updates
            Recovery-->>DemoAPI: Emit recovery_record(COORDINATOR_UNDO)
        end
    end

    Recovery-->>DemoAPI: Emit rto_complete
    Recovery-->>DemoAPI: Return RecoveryResult
    DemoAPI->>State: Persist live recovery events
    loop Replay recovery events with UI delay
        DemoAPI->>WS: Broadcast recovery event
        WS-->>DemoUI: Render timeline/live recovery log
    end
    DemoAPI->>State: Mark node CONSISTENT
    DemoAPI->>WS: Broadcast node_status(CONSISTENT)
    WS-->>DemoUI: Stop stopwatch, update node card
    DemoAPI-->>DemoUI: Return recovery summary
```

## 2. Scenario Flow: Load Curated Scenario

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant DemoUI as Browser UI /demo
    participant DemoAPI as FastAPI Demo Router
    participant ScenarioGen as demo_scenarios.py
    participant State as DemoState
    participant WAL as WAL File
    participant Snapshot as Snapshot File
    participant WS as WebSocket /ws/events

    User->>DemoUI: Select scenario
    User->>DemoUI: Click Load Scenario
    DemoUI->>DemoAPI: POST /api/demo/scenario
    DemoAPI->>State: Activate new scenario run
    DemoAPI->>ScenarioGen: generate_demo_scenario(scenario_id)
    ScenarioGen->>Snapshot: Create deterministic snapshot
    ScenarioGen->>WAL: Write planned WAL records
    alt Fast checkpoint / Heavy redo
        ScenarioGen->>WAL: Write committed transactions and checkpoint markers
    else Global undo
        ScenarioGen->>WAL: Write COMMIT, ABORT, and LOSER transactions
    else 2PC in-doubt
        ScenarioGen->>WAL: Write PREPARE / READY without final decision
    else Checkpoint failure
        ScenarioGen->>WAL: Write BEGIN_CHECKPOINT without END_CHECKPOINT
    end
    DemoAPI->>State: Store scenario metadata and coordinator decisions
    DemoAPI->>WS: Broadcast demo_log_stream_state(running=true)
    DemoAPI->>WS: Broadcast node_status(RUNNING)
    DemoAPI-->>DemoUI: Return scenario status
    DemoUI->>DemoAPI: GET /api/demo/recent-log
    DemoAPI-->>DemoUI: Return live_events or WAL tail
    DemoUI->>DemoUI: Render scenario title, expected result, and Live Log
```

## 3. Live Log Hydration And Reconnect

```mermaid
sequenceDiagram
    autonumber
    participant DemoUI as Browser UI /demo
    participant DemoAPI as FastAPI Demo Router
    participant State as DemoState
    participant WS as WebSocket /ws/events

    DemoUI->>DemoAPI: GET /api/demo/status
    DemoAPI-->>DemoUI: Return current run status
    DemoUI->>WS: Connect /ws/events
    WS-->>DemoUI: Stream future events

    alt log_stream_running is false or page reconnects
        DemoUI->>DemoAPI: GET /api/demo/recent-log?limit=80
        DemoAPI->>State: Read demo_state.live_events
        DemoAPI-->>DemoUI: Return persisted live events
        DemoUI->>DemoUI: Re-render WAL rows, recovery rows, timeline events
    else stream is active
        WS-->>DemoUI: Continue receiving log_entry / recovery events
    end
```

## 4. Benchmark Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant BenchUI as Browser UI /benchmark
    participant BenchAPI as FastAPI Benchmark Router
    participant Task as Background Benchmark Task
    participant Runner as benchmark_runner.py
    participant DataGen as data_gen
    participant Recovery as RecoveryManager
    participant Results as results/raw + summary.csv
    participant WS as WebSocket /ws/events

    User->>BenchUI: Click Run Benchmark
    BenchUI->>BenchAPI: POST /api/benchmark/run
    BenchAPI->>Task: Schedule _run_benchmark_background(config)
    BenchAPI-->>BenchUI: Return running=true

    loop For each checkpoint interval
        loop For each run
            Task->>Runner: run_single_benchmark or run_single_full_scale_benchmark
            alt generated mode
                Runner->>DataGen: generate_logs(interval, seed)
                DataGen-->>Runner: WAL + snapshot
                Runner->>Recovery: recover(log_path, snapshot_path)
                Recovery-->>Runner: RecoveryResult
            else full_scale mode
                Runner->>Runner: Scan WAL window sized by interval
                Runner-->>Task: Estimated recovery work and elapsed scan time
            end
            Runner->>Results: write_raw_result(JSON)
            Task->>WS: Broadcast benchmark_progress
            WS-->>BenchUI: Update progress bar/status
        end
    end

    Task->>Results: analyze_raw_dir(raw, summary.csv)
    Task->>BenchAPI: Mark benchmark_state.running=false
    BenchUI->>BenchAPI: GET /api/benchmark/results
    BenchAPI->>Results: Read summary.csv
    BenchAPI-->>BenchUI: Return summary rows
    BenchUI->>BenchUI: Render RTO chart, cost chart, and table
```

## 5. WAL Log Inspector Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as User
    participant LogsUI as Browser UI /logs
    participant LogsAPI as FastAPI Logs Router
    participant State as DemoState
    participant WAL as Current WAL File

    User->>LogsUI: Open /logs or click Refresh
    LogsUI->>LogsAPI: GET /api/logs/records?offset=0&limit=50
    LogsAPI->>State: Read current demo_state.log_path
    LogsAPI->>WAL: iter_log_records(log_path)
    LogsAPI-->>LogsUI: Return paged WAL records
    LogsUI->>LogsUI: Render LSN, node, TXN, type, page, before/after image

    opt User filters node
        User->>LogsUI: Select node
        LogsUI->>LogsAPI: GET /api/logs/records?node=A&offset=0&limit=50
        LogsAPI->>WAL: Read and filter WAL records by node_id
        LogsAPI-->>LogsUI: Return filtered records
        LogsUI->>LogsUI: Render filtered table
    end

    opt User paginates
        User->>LogsUI: Click Next / Prev
        LogsUI->>LogsAPI: GET /api/logs/records?offset=N&limit=50
        LogsAPI-->>LogsUI: Return requested page
        LogsUI->>LogsUI: Render table page
    end
```
