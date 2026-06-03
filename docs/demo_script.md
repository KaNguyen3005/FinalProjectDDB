# Kịch Bản Quay Demo

Thời lượng mục tiêu: 3 đến 5 phút.

## 1. Chuẩn Bị

Chạy app:

```bash
python run.py
```

Mở các màn hình:

- Demo: `http://127.0.0.1:8000/demo`
- Benchmark: `http://127.0.0.1:8000/benchmark`
- Logs: `http://127.0.0.1:8000/logs`

## 2. Luồng Quay

1. Bắt đầu ở `/demo`.
   - Hiển thị cụm 3 node.
   - Chỉ ra checkpoint interval control và WAL stream hiện tại.

2. Áp dụng checkpoint interval.
   - Chọn interval ngắn như 1 hoặc 2 phút.
   - Bấm `Apply Config` để demo log được generate lại.

3. Hiển thị WAL records.
   - Để live log panel hiển thị `START`, `UPDATE`, `COMMIT`, checkpoint, `PREPARE` và `READY`.
   - Giải thích rằng `PREPARE`/`READY` được dùng để tạo tình huống `in-doubt transaction` sau failure.

4. Crash Node A.
   - Bấm `Crash Node A`.
   - Hiển thị Node A chuyển sang crashed state và RTO timer bắt đầu.

5. Chạy recovery.
   - Bấm `Recover`.
   - Hiển thị các phase `Analysis`, `Partial Redo`, `Global Undo` và event `in-doubt transaction` nếu có.
   - Dừng ở final RTO value và consistent status.

6. Chuyển sang `/benchmark`.
   - Hiển thị chart RTO vs interval.
   - Hiển thị cost breakdown chart.
   - Hiển thị bảng mean, median, P99 và standard deviation.

7. Chuyển nhanh sang `/logs`.
   - Hiển thị WAL inspection có phân trang.
   - Nhắc rằng màn hình này dùng để đối chiếu record type và `LSN`.

## 3. Ý Chính Khi Thuyết Minh

- Independent variable là checkpoint interval.
- Dependent metric là RTO tính bằng giây.
- `BEGIN_CHECKPOINT` và `END_CHECKPOINT` giới hạn lượng WAL cần scan sau crash.
- `Partial Redo` bảo vệ durability cho committed transactions.
- `Global Undo` bảo vệ atomicity cho incomplete transactions.
- `PREPARE`/`READY` không có `COMMIT`/`ABORT` là `in-doubt` và cần coordinator resolution.
- Full benchmark command dùng 10 runs mỗi interval để kết quả ổn định hơn về thống kê.

## 4. Gợi Ý Nhịp Nói

- 30 giây đầu: giới thiệu bài toán và màn hình demo.
- 60-90 giây tiếp theo: tạo log, crash node và chạy recovery.
- 60 giây tiếp theo: giải thích các phase recovery.
- 60 giây cuối: chuyển sang benchmark và logs, kết luận về checkpoint interval và RTO.
