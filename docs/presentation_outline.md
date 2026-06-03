# Dàn Ý Thuyết Trình

## Slide 1: Câu Hỏi Dự Án

Tiêu đề: `RTO Benchmark for Disaster Recovery`

- Câu hỏi: checkpoint interval ảnh hưởng như thế nào đến node recovery time?
- Metric: mean, median và P99 RTO.
- Hệ thống: simulated distributed database node với WAL, checkpoints và 2PC records.

## Slide 2: Mục Tiêu

- Xây dựng simulator crash/recovery có thể chạy trên laptop.
- Minh họa quan hệ giữa checkpoint interval và RTO.
- Tạo benchmark pipeline có raw results, summary CSV và charts.
- Cung cấp UI demo realtime để quan sát WAL, crash và recovery phases.

## Slide 3: Kiến Trúc

- Browser UI: demo, benchmark, WAL inspector.
- FastAPI backend: REST control/results và WebSocket live events.
- Core engine: WAL, snapshot storage, checkpoint manager, recovery manager.
- Outputs: raw JSON, summary CSV, generated charts.

## Slide 4: WAL Và Snapshot

- WAL lưu các record `START`, `UPDATE`, `COMMIT`, `ABORT`, checkpoint, `PREPARE`, `READY`.
- `UPDATE` chứa `before_image` và `after_image`.
- Snapshot được mô phỏng bằng binary pages, mỗi page là số nguyên 64-bit.
- `redo` ghi `after_image`; `undo` ghi `before_image`.

## Slide 5: Recovery Algorithm

- `Analysis` bắt đầu từ `END_CHECKPOINT` hợp lệ mới nhất.
- `Partial Redo` áp dụng lại `after_image` cho committed transactions.
- `Global Undo` khôi phục `before_image` cho loser hoặc aborted transactions.
- `PREPARE`/`READY` không có quyết định cuối trở thành `in-doubt`.

## Slide 6: Experiment Design

- Independent variable: checkpoint interval.
- Controlled variables: seed, transaction count, snapshot page count, transaction rate.
- Full matrix: intervals 1, 2, 5, 10, 20, 30 phút x 10 runs.
- Statistics: mean, median, P99, standard deviation.

## Slide 7: Cost Model

```text
Cost = C_io * #IO + C_cpu * #cpu + C_msg * #messages + C_tr * #bytes
```

- `#IO` tăng theo log bytes kể từ checkpoint.
- `#cpu` tăng theo số recovery records được xử lý.
- `#messages` tăng khi `in-doubt transactions` cần coordinator resolution.

## Slide 8: Results

Sử dụng:

- `results/charts/rto_vs_interval.svg`
- `results/charts/cost_breakdown.svg`
- `results/charts/rto_heatmap.svg`

Ý chính: smoke baseline xác nhận pipeline hoạt động; full matrix cần thiết để đưa ra kết luận thống kê cuối cùng.

## Slide 9: Demo

- Crash Node A.
- Recover và hiển thị `Analysis`, `Partial Redo`, `Global Undo`.
- Hiển thị RTO completion và benchmark dashboard.
- Mở WAL inspector để đối chiếu record thực tế.

## Slide 10: Giới Hạn

- Snapshot page là scalar value, không phải database page thật.
- Checkpoint metadata được đơn giản hóa.
- Cost model là proxy để so sánh xu hướng, không thay thế benchmark production.
- Simulator tập trung vào logic recovery, không mô phỏng đầy đủ distributed database runtime.

## Slide 11: Kết Luận

- Project triển khai crash recovery end to end.
- Checkpoint interval trực tiếp kiểm soát recovery scan length.
- Benchmark kết nối measured RTO với distributed cost model.
- Xử lý `in-doubt transaction` minh họa distributed recovery case, không chỉ local WAL recovery.
