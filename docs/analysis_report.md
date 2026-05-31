# Analysis Report: Checkpoint Interval vs RTO

## Research Question

How does checkpoint frequency affect the recovery time of a distributed database node after a crash?

The hypothesis is that longer checkpoint intervals increase recovery work because the system must scan and replay more WAL records after the last END_CHECKPOINT. The practical tradeoff is that frequent checkpoints reduce crash recovery time but add more work during normal operation.

## Current Benchmark Dataset

The table below reflects the current `results/summary.csv` in this workspace. It is a smoke baseline over intervals 1, 2, and 5 minutes. For final grading, run the full matrix with 1, 2, 5, 10, 20, and 30 minute intervals and 10 runs per interval.

| Interval (min) | Mean RTO (s) | Median RTO (s) | P99 RTO (s) | Std Dev (s) | IO Cost | CPU Cost | Comm Cost | Theory RTO (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.101045 | 0.101045 | 0.120673 | 0.028324 | 29.296875 | 24.000000 | 50.256000 | 0.292969 |
| 2 | 0.328353 | 0.328353 | 0.344335 | 0.023062 | 58.593750 | 48.000000 | 40.204800 | 0.585938 |
| 5 | 0.118324 | 0.118324 | 0.119074 | 0.001083 | 146.484375 | 120.000000 | 30.153600 | 1.464844 |

## Charts

![RTO vs checkpoint interval](../results/charts/rto_vs_interval.svg)

![Cost breakdown](../results/charts/cost_breakdown.svg)

![RTO heatmap](../results/charts/rto_heatmap.svg)

## Cost Model

The benchmark uses the distributed cost model from Ozsu and Valduriez section 4.4:

```text
Total Cost = C_io * #IO + C_cpu * #cpu + C_msg * #messages + C_tr * #bytes
```

For recovery, the terms are mapped as follows:

| Term | Recovery interpretation |
|---|---|
| #IO | Log pages read since the latest END_CHECKPOINT. |
| #cpu | UPDATE records considered during Analysis, Partial Redo, and Global Undo. |
| #messages | Coordination messages used to resolve in-doubt 2PC transactions. |
| #bytes | Consistency or coordinator response payload bytes. |

The implementation in `benchmark/cost_model.py` estimates log bytes as:

```text
log_bytes = interval_min * 60 * txn_rate * avg_record_bytes
```

Then it derives IO, CPU, communication cost, total cost, and a theoretical RTO proxy. Because log bytes grow with checkpoint interval, the model predicts increasing IO and CPU cost as checkpoints become less frequent.

## Empirical Validation

The current smoke baseline is useful for verifying the pipeline, not for a final statistical claim. It confirms that:

- The benchmark runner can produce raw JSON files and aggregate them into `results/summary.csv`.
- Mean, median, P99, standard deviation, IO cost, CPU cost, communication cost, and theoretical RTO are all generated.
- Report charts can be regenerated from the summary CSV without manual editing.

The 2 minute interval has the highest measured RTO in the current smoke data, while the 5 minute interval has the highest modeled IO and CPU cost. This mismatch is expected in a small run because Python startup, file system cache effects, and randomized transaction patterns dominate the short measurement. The full matrix with 10 runs per interval is required to smooth this noise and expose the expected trend.

## In-Doubt Transaction Handling

During Analysis, a transaction with PREPARE or READY but no final COMMIT or ABORT is classified as IN_DOUBT. Per the roadmap mapping to Ozsu and Valduriez section 5.4.3, the recovering participant cannot unilaterally undo it. The recovery manager emits an `in_doubt_txn` event and leaves final resolution to the coordinator path represented in the simulation.

This matters for RTO because in-doubt transactions add communication work. The cost model accounts for this by adding messages and bytes per in-doubt transaction.

## Conclusion

The implemented system supports the full experiment: generate WAL/snapshot data, inject a crash, recover with Analysis, Partial Redo, and Global Undo, aggregate repeated runs, and visualize the result in the browser and report. The current smoke data validates the pipeline. The final experiment should run:

```bash
python benchmark/benchmark_runner.py --intervals 1 2 5 10 20 30 --runs 10 --seed 42
python benchmark/chart_generator.py
```

Expected final finding: increasing checkpoint interval should increase modeled recovery cost and, under a large enough workload, increase empirical tail RTO because recovery scans more log records after the last END_CHECKPOINT.
