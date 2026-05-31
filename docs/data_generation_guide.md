# Data Generation Guide

## Read in this order

1. `data_gen/generate_snapshot.py`
   - Generates the base snapshot file.
   - This is the starting image before any WAL replay.

2. `data_gen/generate_logs.py`
   - Generates a pseudo-random WAL on top of that snapshot.
   - Look for START, UPDATE, COMMIT, ABORT, PREPARE, and READY.
   - This file is the best place to understand how synthetic transactions are built.

3. `data_gen/demo_scenarios.py`
   - Generates deterministic demo cases.
   - Each branch maps to one story: clean recovery, heavy redo, Global Undo, in-doubt 2PC, or checkpoint failure.

4. `data_gen/generate_full_scale_dataset.py`
   - Builds the large benchmark dataset.
   - Focus on `build_log_pattern()` and `create_large_wal()` to understand record alignment.

## How to read the flow

- Snapshot first: the data file is created before the WAL.
- WAL second: transactions append START/UPDATE/COMMIT/ABORT records.
- Checkpoints: inserted periodically so recovery can start from the latest valid checkpoint.
- Demo scenarios: deterministic branches for presentation and testing.
- Full-scale dataset: repeated pattern, not random, so size and record mix are predictable.

## Quick mental model

```text
snapshot -> checkpoint -> transaction updates -> decision -> next checkpoint
```

If you want to trace one transaction, read `generate_logs.py` first.
If you want to trace one demo story, read `demo_scenarios.py` first.
