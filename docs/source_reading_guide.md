# Hướng Dẫn Đọc Source Code

Tài liệu này hướng dẫn đọc source theo luồng logic, không đọc theo thứ tự alphabet. Nên đọc theo các vòng: vòng tổng quan, vòng WAL và recovery, vòng API/UI, vòng benchmark.

## 1. Vòng 15 Phút Đầu

Bắt đầu với các file này:

1. `README.md`
2. `run.py`
3. `api/app.py`
4. `src/main.py`

Sau vòng này, bạn cần nắm được:

- App chạy bằng `python run.py`.
- FastAPI app nằm ở `api.app:app`.
- CLI recovery nằm ở `src/main.py`.
- Project có 3 màn hình UI: demo, benchmark, logs.
- Core recovery không nằm trong API mà nằm trong `src/recovery/recovery_manager.py`.

## 2. Đường Đọc Quan Trọng Nhất: WAL Và Recovery

Đọc theo thứ tự:

1. `src/log/log_record.py`
2. `src/storage.py`
3. `src/checkpoint/checkpoint_manager.py`
4. `data_gen/generate_logs.py`
5. `src/recovery/recovery_manager.py`

### 2.1. `src/log/log_record.py`

Đây là file nên đọc đầu tiên nếu muốn hiểu recovery.

Cần chú ý:

- `RecordType`: các loại record trong WAL.
- `LogRecord.STRUCT`: binary format của mỗi record.
- `lsn`: số thứ tự log, tăng dần.
- `before_image`: giá trị dùng cho `undo`.
- `after_image`: giá trị dùng cho `redo`.
- `redo_lsn`: điểm recovery bắt đầu sau checkpoint.
- `WalWriter.append()`: mỗi lần append tạo một `LSN` mới.
- `iter_log_records()`: đọc WAL thành các `LogRecord`.

Nếu chưa hiểu `before_image` và `after_image`, nên dừng lại ở đây. Hai field này là chìa khóa của `redo` và `undo`.

### 2.2. `src/storage.py`

File này nhỏ nhưng quan trọng. Nó cho thấy snapshot được mô phỏng như một mảng page trong file nhị phân.

Cần chú ý:

- Mỗi page là một số nguyên 64-bit.
- `read_page()` đọc page theo offset.
- `write_page()` ghi giá trị mới vào page.
- Recovery thực sự thay đổi snapshot bằng `write_page()`.

### 2.3. `src/checkpoint/checkpoint_manager.py`

Checkpoint trong simulator là cặp record:

- `BEGIN_CHECKPOINT`
- `END_CHECKPOINT`

`END_CHECKPOINT.redo_lsn` cho recovery biết nên bắt đầu scan lại từ đâu.

Đọc thêm tham số `fail_after_begin`: tham số này tạo tình huống crash sau `BEGIN_CHECKPOINT` nhưng trước `END_CHECKPOINT`.

### 2.4. `data_gen/generate_logs.py`

File này trả lời câu hỏi: WAL và snapshot được tạo ra như thế nào?

Cần chú ý:

- Generator tạo snapshot mới.
- Mỗi transaction ghi `START`, `UPDATE`, rồi `COMMIT`/`ABORT`/`PREPARE`/`READY`.
- Một số update được ghi ngay vào snapshot để recovery có việc phải `undo`.
- Checkpoint được ghi định kỳ theo `checkpoint_every`.

### 2.5. `src/recovery/recovery_manager.py`

Đây là file trung tâm của project.

Đọc `recover()` trước, sau đó mới đọc các hàm private theo đúng thứ tự nó gọi:

1. `_analysis_pass()`
2. `_detect_checkpoint_failure()`
3. `_partial_redo()`
4. `_global_undo()`
5. `_handle_in_doubt()`
6. `_resolve_in_doubt()`

Khi đọc, hãy tự vẽ bảng transaction state:

```text
START        -> LOSER
PREPARE      -> IN_DOUBT
READY        -> IN_DOUBT nếu chưa có state
COMMIT       -> COMMITTED
ABORT        -> ABORTED
```

Quy tắc phục hồi:

- `COMMITTED`: redo `UPDATE` bằng `after_image`.
- `LOSER`/`ABORTED`: undo `UPDATE` bằng `before_image`.
- `IN_DOUBT`: không tự quyết, hỏi coordinator nếu có.

## 3. Đường Đọc Demo Realtime

Đọc theo thứ tự:

1. `data_gen/demo_scenarios.py`
2. `api/state.py`
3. `api/routers/demo.py`
4. `api/websocket/events.py`
5. `api/websocket/manager.py`
6. `ui/js/ws-client.js`
7. `ui/js/demo.js`
8. `ui/demo.html`

### 3.1. `data_gen/demo_scenarios.py`

File này tạo các WAL có chủ đích:

- checkpoint nhanh, recovery sạch
- checkpoint dài, redo nhiều
- loser transaction cần `Global Undo`
- `2PC in-doubt transaction`
- checkpoint failure

Nên đọc `SCENARIOS` trước, sau đó đọc `generate_demo_scenario()`, cuối cùng đọc `_write_plan()`.

### 3.2. `api/routers/demo.py`

File này là bộ điều khiển demo.

Endpoint cần nắm:

- `GET /api/demo/status`
- `GET /api/demo/scenarios`
- `POST /api/demo/scenario`
- `POST /api/demo/config`
- `POST /api/demo/crash`
- `POST /api/demo/recover`
- `POST /api/demo/recover-interrupted`
- `GET /api/demo/recent-log`

Luồng chạy:

1. Load scenario.
2. Restart log stream.
3. Broadcast WAL entries.
4. Crash node.
5. Run recovery.
6. Broadcast recovery events theo từng bước.

### 3.3. WebSocket Files

`api/websocket/events.py` tạo payload dict chuẩn cho UI.

`api/websocket/manager.py` giữ danh sách WebSocket connection và broadcast event cho tất cả client.

`ui/js/ws-client.js` là client dùng chung để browser nhận event.

## 4. Đường Đọc Benchmark

Đọc theo thứ tự:

1. `benchmark/benchmark_runner.py`
2. `benchmark/stats_analyzer.py`
3. `benchmark/cost_model.py`
4. `benchmark/chart_generator.py`
5. `api/routers/benchmark.py`
6. `ui/js/benchmark.js`
7. `ui/benchmark.html`

### 4.1. `benchmark/benchmark_runner.py`

Đọc các hàm:

- `run_single_benchmark()`: sinh data mới và recovery thật.
- `run_single_full_scale_benchmark()`: scan dataset lớn.
- `_scan_full_scale_window()`: đếm committed/aborted/in-doubt trong cửa sổ log.
- `write_raw_result()`: ghi raw JSON.
- `run_benchmark_matrix()`: chạy toàn bộ `intervals x runs`.

Cần hiểu công thức seed:

```text
run_seed = seed + interval * 10000 + run
```

Công thức này giúp mỗi interval/run có data riêng nhưng vẫn tái lập được.

### 4.2. `benchmark/stats_analyzer.py`

File này gom raw JSON theo `interval_min`, tính thống kê và ghi `summary.csv`.

Nếu chỉ cần hiểu output benchmark, đọc:

- `SUMMARY_FIELDS`
- `summarize_results()`
- `write_summary_csv()`

### 4.3. `api/routers/benchmark.py`

File này bọc benchmark CLI thành API async. Vì benchmark có thể tốn thời gian, API chạy nó trong background task và broadcast tiến độ qua WebSocket.

## 5. Đường Đọc Log Inspector

Đọc theo thứ tự:

1. `api/routers/logs.py`
2. `src/log/log_record.py`
3. `ui/js/logs.js`
4. `ui/logs.html`

Điểm cần nắm:

- API đọc WAL bằng iterator trong `src/log/log_record.py`.
- UI phân trang và hiển thị record theo loại.
- Log inspector hữu ích khi cần đối chiếu event demo với record thật trong WAL.

## 6. Cách Tự Kiểm Tra Hiểu Đúng

Sau khi đọc source, thử trả lời các câu hỏi sau:

- `END_CHECKPOINT.redo_lsn` ảnh hưởng gì đến lượng WAL cần scan?
- Vì sao committed transaction cần `redo`?
- Vì sao loser transaction cần `undo`?
- Vì sao `PREPARE`/`READY` nhưng chưa có `COMMIT`/`ABORT` lại thành `IN_DOUBT`?
- UI nhận recovery progress qua REST API hay WebSocket?
- Benchmark khác demo realtime ở điểm nào?

Nếu trả lời được các câu trên, bạn đã nắm được logic chính của source code.
