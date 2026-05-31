# Screen Recording Script

Target length: 3 to 5 minutes.

## Setup

```bash
python run.py
```

Open:

- Demo: `http://127.0.0.1:8000/demo`
- Benchmark: `http://127.0.0.1:8000/benchmark`
- Logs: `http://127.0.0.1:8000/logs`

## Recording Flow

1. Start on `/demo`.
   - Show the three-node cluster.
   - Point out checkpoint interval control and current WAL stream.

2. Apply a checkpoint interval.
   - Select a short interval such as 1 or 2 minutes.
   - Click Apply Config so the demo log is regenerated.

3. Show WAL records.
   - Let the live log panel show START, UPDATE, COMMIT, checkpoint, PREPARE, and READY records.
   - Mention that PREPARE/READY are used to surface in-doubt transactions after failure.

4. Crash Node A.
   - Click Crash Node A.
   - Show Node A transitioning to crashed state and the RTO timer beginning.

5. Recover.
   - Click Recover.
   - Show Analysis, Partial Redo, Global Undo, and any in-doubt transaction events.
   - Stop on the final RTO value and consistent status.

6. Switch to `/benchmark`.
   - Show RTO vs interval chart.
   - Show cost breakdown chart.
   - Show table with mean, median, P99, and standard deviation.

7. Switch briefly to `/logs`.
   - Show paginated WAL inspection and record type filtering context.

## Narration Points

- The independent variable is checkpoint interval.
- The dependent metric is RTO in seconds.
- BEGIN_CHECKPOINT and END_CHECKPOINT bound the amount of WAL scanned after crash.
- Partial Redo protects durability for committed transactions.
- Global Undo protects atomicity for incomplete transactions.
- PREPARE/READY without COMMIT/ABORT is in-doubt and requires coordinator resolution.
- Full benchmark command uses 10 runs per interval for statistical stability.
