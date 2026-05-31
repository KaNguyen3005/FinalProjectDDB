# Presentation Outline

## Slide 1: Project Question

Title: RTO Benchmark for Disaster Recovery

- Question: how does checkpoint interval affect node recovery time?
- Metric: mean, median, and P99 RTO.
- System: simulated distributed database node with WAL, checkpoints, and 2PC records.

## Slide 2: Architecture

- Browser UI: demo, benchmark, WAL inspector.
- FastAPI backend: REST control/results and WebSocket live events.
- Core engine: WAL, snapshot storage, checkpoint manager, recovery manager.
- Outputs: raw JSON, summary CSV, generated charts.

## Slide 3: Recovery Algorithm

- Analysis starts from latest END_CHECKPOINT.
- Partial Redo reapplies after images for committed transactions.
- Global Undo restores before images for loser or aborted transactions.
- PREPARE/READY without final decision becomes in-doubt.

## Slide 4: Experiment Design

- Independent variable: checkpoint interval.
- Controlled variables: seed, transaction count, snapshot page count, transaction rate.
- Full matrix: intervals 1, 2, 5, 10, 20, 30 minutes x 10 runs.
- Statistics: mean, median, P99, standard deviation.

## Slide 5: Cost Model

```text
Cost = C_io * #IO + C_cpu * #cpu + C_msg * #messages + C_tr * #bytes
```

- #IO grows with log bytes since checkpoint.
- #cpu grows with recovery records processed.
- #messages grows when in-doubt transactions require coordinator resolution.

## Slide 6: Results

Use:

- `results/charts/rto_vs_interval.svg`
- `results/charts/cost_breakdown.svg`
- `results/charts/rto_heatmap.svg`

Main point: the smoke baseline validates the pipeline; the full matrix is needed for the final statistical claim.

## Slide 7: Demo

- Crash Node A.
- Recover and show Analysis, Partial Redo, Global Undo.
- Show RTO completion and benchmark dashboard.

## Slide 8: Conclusion

- The project implements crash recovery end to end.
- Checkpoint interval directly controls recovery scan length.
- The benchmark connects measured RTO to the distributed cost model.
- In-doubt transaction handling demonstrates the distributed recovery case, not only local WAL recovery.
