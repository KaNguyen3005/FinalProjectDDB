# Báo Cáo Phân Tích: Checkpoint Interval Và RTO

## 1. Câu Hỏi Nghiên Cứu

`Checkpoint frequency` ảnh hưởng như thế nào đến thời gian recovery của một distributed database node sau crash?

Giả thuyết của dự án: `checkpoint interval` càng dài thì recovery work càng tăng, vì hệ thống phải scan và replay nhiều WAL records hơn kể từ `END_CHECKPOINT` hợp lệ gần nhất. Tradeoff thực tế là checkpoint thường xuyên giúp giảm crash recovery time, nhưng làm tăng công việc trong quá trình vận hành bình thường.

## 2. Benchmark Dataset Hiện Tại

Bảng dưới đây phản ánh `results/summary.csv` hiện tại trong workspace. Đây là smoke baseline với các interval 1, 2 và 5 phút. Để có kết quả cuối cùng cho báo cáo, cần chạy full matrix với interval 1, 2, 5, 10, 20 và 30 phút, mỗi interval 10 runs.

| Interval (min) | Mean RTO (s) | Median RTO (s) | P99 RTO (s) | Std Dev (s) | IO Cost | CPU Cost | Comm Cost | Theory RTO (s) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.101045 | 0.101045 | 0.120673 | 0.028324 | 29.296875 | 24.000000 | 50.256000 | 0.292969 |
| 2 | 0.328353 | 0.328353 | 0.344335 | 0.023062 | 58.593750 | 48.000000 | 40.204800 | 0.585938 |
| 5 | 0.118324 | 0.118324 | 0.119074 | 0.001083 | 146.484375 | 120.000000 | 30.153600 | 1.464844 |

## 3. Charts

![RTO vs checkpoint interval](../results/charts/rto_vs_interval.svg)

![Cost breakdown](../results/charts/cost_breakdown.svg)

![RTO heatmap](../results/charts/rto_heatmap.svg)

## 4. Cost Model

Benchmark dùng distributed cost model từ Ozsu và Valduriez section 4.4:

```text
Total Cost = C_io * #IO + C_cpu * #cpu + C_msg * #messages + C_tr * #bytes
```

Trong recovery, các thành phần được mapping như sau:

| Term | Diễn giải trong recovery |
|---|---|
| `#IO` | Số log pages cần đọc kể từ `END_CHECKPOINT` mới nhất. |
| `#cpu` | Số `UPDATE` records được xét trong `Analysis`, `Partial Redo` và `Global Undo`. |
| `#messages` | Coordination messages dùng để resolve `in-doubt 2PC transactions`. |
| `#bytes` | Consistency hoặc coordinator response payload bytes. |

Implementation trong `benchmark/cost_model.py` ước lượng log bytes bằng:

```text
log_bytes = interval_min * 60 * txn_rate * avg_record_bytes
```

Sau đó cost model suy ra IO cost, CPU cost, communication cost, total cost và theoretical RTO proxy. Vì log bytes tăng theo checkpoint interval, model dự đoán IO và CPU cost tăng khi checkpoint ít thường xuyên hơn.

## 5. Empirical Validation

Smoke baseline hiện tại hữu ích để kiểm tra pipeline, nhưng chưa đủ để đưa ra kết luận thống kê cuối cùng. Kết quả hiện tại xác nhận rằng:

- Benchmark runner có thể tạo raw JSON files và tổng hợp thành `results/summary.csv`.
- Mean, median, P99, standard deviation, IO cost, CPU cost, communication cost và theoretical RTO đều được tạo.
- Report charts có thể regenerate từ summary CSV mà không cần chỉnh tay.

Trong smoke data hiện tại, interval 2 phút có measured RTO cao nhất, trong khi interval 5 phút có modeled IO và CPU cost cao nhất. Sự lệch này là hợp lý ở run nhỏ, vì Python startup, file system cache và randomized transaction patterns có thể chi phối các phép đo rất ngắn. Full matrix với 10 runs mỗi interval cần được chạy để làm mượt noise và làm rõ xu hướng kỳ vọng.

## 6. In-Doubt Transaction Handling

Trong `Analysis`, transaction có `PREPARE` hoặc `READY` nhưng không có `COMMIT`/`ABORT` cuối cùng được phân loại là `IN_DOUBT`. Theo mapping với Ozsu và Valduriez section 5.4.3, participant đang recovery không được tự ý undo transaction đó, vì quyết định global có thể đã là commit.

Recovery manager phát event `in_doubt_txn` và chuyển quyết định cuối sang coordinator path trong simulation.

Điều này ảnh hưởng đến RTO vì `in-doubt transactions` thêm communication work. Cost model phản ánh việc này bằng cách cộng messages và bytes cho mỗi in-doubt transaction.

## 7. Kết Luận

Hệ thống đã hỗ trợ đầy đủ experiment: sinh WAL/snapshot data, inject crash, recover với `Analysis`, `Partial Redo` và `Global Undo`, tổng hợp repeated runs và visualize result trong browser cũng như report. Smoke data hiện tại xác nhận pipeline hoạt động.

Experiment cuối nên chạy:

```bash
python benchmark/benchmark_runner.py --intervals 1 2 5 10 20 30 --runs 10 --seed 42
python benchmark/chart_generator.py
```

Kỳ vọng kết quả cuối: checkpoint interval tăng sẽ làm modeled recovery cost tăng; với workload đủ lớn, empirical tail RTO cũng sẽ tăng vì recovery phải scan nhiều log records hơn sau `END_CHECKPOINT` gần nhất.
