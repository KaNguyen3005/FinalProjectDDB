# Hướng Dẫn Sinh Dữ Liệu

Tài liệu này giải thích cách đọc và sử dụng các script trong `data_gen/`. Mục tiêu là hiểu WAL, snapshot và demo scenario được tạo ra như thế nào.

## 1. Nên Đọc Theo Thứ Tự Này

1. `data_gen/generate_snapshot.py`
   - Tạo base snapshot file.
   - Đây là ảnh dữ liệu ban đầu trước khi replay WAL.

2. `data_gen/generate_logs.py`
   - Tạo pseudo-random WAL dựa trên snapshot.
   - Tìm các record `START`, `UPDATE`, `COMMIT`, `ABORT`, `PREPARE` và `READY`.
   - Đây là file quan trọng nhất để hiểu synthetic transactions được dựng như thế nào.

3. `data_gen/demo_scenarios.py`
   - Tạo deterministic demo cases.
   - Mỗi branch tương ứng một câu chuyện: clean recovery, heavy redo, `Global Undo`, `in-doubt 2PC` hoặc checkpoint failure.

4. `data_gen/generate_full_scale_dataset.py`
   - Tạo large benchmark dataset.
   - Tập trung vào `build_log_pattern()` và `create_large_wal()` để hiểu record alignment.

## 2. Luồng Sinh Dữ Liệu

- Snapshot được tạo trước: data file tồn tại trước WAL.
- WAL được tạo sau: transactions append `START`/`UPDATE`/`COMMIT`/`ABORT` records.
- Checkpoints được chèn định kỳ để recovery có thể bắt đầu từ checkpoint hợp lệ mới nhất.
- Demo scenarios dùng deterministic branches để phục vụ presentation và testing.
- Full-scale dataset dùng pattern lặp, không hoàn toàn random, để kích thước và record mix có thể dự đoán được.

## 3. Mental Model Nhanh

```text
snapshot -> checkpoint -> transaction updates -> decision -> next checkpoint
```

Nếu muốn trace một transaction ngẫu nhiên, đọc `generate_logs.py` trước.

Nếu muốn trace một demo story, đọc `demo_scenarios.py` trước.

## 4. Ý Nghĩa Seed

Các generator dùng seed để có thể tái lập dữ liệu. Cùng một seed và cùng tham số đầu vào sẽ tạo cùng kiểu workload, giúp benchmark dễ kiểm tra lại.

Trong benchmark, seed thường được suy ra theo công thức:

```text
run_seed = seed + interval * 10000 + run
```

Cách này giúp mỗi interval/run có dataset riêng nhưng vẫn tái lập được.

## 5. Ý Nghĩa Checkpoint Interval

`checkpoint interval` quyết định khoảng cách giữa các checkpoint trong workload. Interval ngắn thường làm recovery scan ít WAL hơn, nhưng checkpoint xảy ra thường xuyên hơn trong runtime bình thường. Interval dài giảm tần suất checkpoint, nhưng sau crash recovery có thể phải đọc nhiều WAL records hơn.

## 6. Lệnh Thường Dùng

Tạo full-scale dataset:

```bash
python data_gen/generate_full_scale_dataset.py --output-dir data/full_scale
```

Chạy benchmark với các interval chuẩn:

```bash
python benchmark/benchmark_runner.py --intervals 1 2 5 10 20 30 --runs 10 --seed 42
```

Generate charts từ summary:

```bash
python benchmark/chart_generator.py
```
