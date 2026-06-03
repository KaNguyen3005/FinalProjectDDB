# Báo Cáo Kiến Trúc Hệ Thống

## 1. Tổng Quan

Dự án này là một simulator và bộ benchmark cho `Recovery Time Objective` (`RTO`) trong một hệ thống database phân tán giả lập. Mục tiêu chính là quan sát `checkpoint interval` ảnh hưởng như thế nào đến thời gian `recovery` sau khi một node bị crash.

Hệ thống gồm 6 lớp chính:

- Core recovery engine trong `src/`
- FastAPI backend trong `api/`
- WebSocket event stream cho UI realtime
- Browser UI trong `ui/`
- Benchmark và thống kê trong `benchmark/`
- Data generation và demo scenario trong `data_gen/`

Cần phân biệt rõ: đây là simulator phục vụ học thuật, demo và benchmark. Dự án không phải là distributed database production.

## 2. Kiến Trúc Thư Mục

`run.py` là entry point để khởi động web app FastAPI.

`src/` chứa logic cốt lõi:

- `src/log/log_record.py`: định nghĩa binary WAL record, `RecordType`, `LSN` và writer/reader.
- `src/storage.py`: thao tác snapshot page đơn giản bằng file nhị phân.
- `src/checkpoint/checkpoint_manager.py`: ghi `BEGIN_CHECKPOINT` và `END_CHECKPOINT`.
- `src/recovery/recovery_manager.py`: thuật toán recovery gồm `Analysis`, `Partial Redo`, `Global Undo` và xử lý `in-doubt transaction`.
- `src/coordinator/coordinator.py`: coordinator simulator cho quyết định `2PC`.
- `src/crash/`: tiện ích crash injection và đo thời gian recovery.
- `src/integrity/`: checksum snapshot.

`api/` chứa backend:

- `api/app.py`: tạo FastAPI app, gắn REST router, static UI và WebSocket.
- `api/state.py`: trạng thái runtime của demo và benchmark.
- `api/routers/demo.py`: API điều khiển demo scenario, crash và recover.
- `api/routers/benchmark.py`: API chạy benchmark nền và lấy kết quả.
- `api/routers/logs.py`: API xem WAL records.
- `api/websocket/events.py`: factory tạo event payload.
- `api/websocket/manager.py`: quản lý WebSocket clients.

`benchmark/` chứa pipeline benchmark:

- `benchmark_runner.py`: chạy ma trận `checkpoint interval x run`.
- `stats_analyzer.py`: tổng hợp raw JSON thành summary CSV.
- `cost_model.py`: ước lượng chi phí I/O, CPU, communication và theoretical RTO.
- `chart_generator.py`: sinh chart từ summary.

`data_gen/` chứa bộ sinh dữ liệu:

- `generate_logs.py`: sinh WAL và snapshot ngẫu nhiên có thể tái lập bằng seed.
- `demo_scenarios.py`: sinh các scenario có chủ đích cho UI demo.
- `generate_full_scale_dataset.py`: sinh dataset lớn.
- `generate_snapshot.py`: tạo snapshot riêng.

`ui/` chứa frontend tĩnh bằng HTML/CSS/vanilla JavaScript:

- `demo.html`: dashboard demo crash/recovery.
- `benchmark.html`: dashboard benchmark.
- `logs.html`: WAL inspector.
- `ui/js/ws-client.js`: WebSocket client dùng chung.
- `ui/js/demo.js`, `benchmark.js`, `logs.js`: logic từng màn hình.

`tests/` là pytest suite bảo vệ format WAL, recovery, API, benchmark và data generation.

## 3. Kiến Trúc Runtime

Khi chạy:

```bash
python run.py
```

`run.py` gọi `uvicorn.run("api.app:app")`. FastAPI app được tạo trong `api/app.py` bằng `create_app()`.

App gắn các route chính:

- `/api/health`: health check.
- `/api/demo/*`: demo scenario, crash và recover.
- `/api/benchmark/*`: benchmark run, status và results.
- `/api/logs/*`: đọc và stream WAL records.
- `/ws/events`: WebSocket event stream.
- `/demo`, `/benchmark`, `/logs`: trả về UI HTML.

UI gọi REST API để bắt đầu hành động, sau đó lắng nghe WebSocket để hiển thị node status, WAL log entries, recovery pass và benchmark progress.

## 4. Mô Hình Dữ Liệu

Snapshot là file nhị phân gồm nhiều page. Trong simulator, mỗi page là một số nguyên 64-bit. `src/storage.py` đọc/ghi page bằng offset:

```text
offset = page_id * 8
```

WAL là file nhị phân record-aligned. Mỗi record có kích thước cố định `LogRecord.SIZE`.

Mỗi `LogRecord` có các trường quan trọng:

- `record_type`: `START`, `UPDATE`, `COMMIT`, `ABORT`, `BEGIN_CHECKPOINT`, `END_CHECKPOINT`, `PREPARE`, `READY`.
- `lsn`: log sequence number tăng dần.
- `txn_id`: transaction id.
- `page_id`: page bị sửa, chỉ có ý nghĩa với `UPDATE`.
- `before_image`: giá trị trước update, dùng cho `undo`.
- `after_image`: giá trị sau update, dùng cho `redo`.
- `redo_lsn`: điểm bắt đầu redo ghi trong `END_CHECKPOINT`.
- `node_id`: node phát sinh record.
- `timestamp`: thời điểm tạo record.

## 5. Luồng Sinh Dữ Liệu

`data_gen/generate_logs.py` tạo snapshot mới, xóa WAL cũ, rồi sinh transaction:

1. Ghi checkpoint ban đầu.
2. Với mỗi transaction, ghi `START`.
3. Ghi 1 đến 3 `UPDATE`.
4. Một số update được flush vào snapshot để tạo tình huống cần `undo`.
5. Kết thúc bằng `COMMIT`, `ABORT` hoặc `PREPARE`/`READY`.
6. Định kỳ ghi checkpoint theo `checkpoint_every`.

`data_gen/demo_scenarios.py` khác với generator ngẫu nhiên: file này tạo WAL theo kịch bản có chủ đích để minh họa từng trường hợp recovery.

## 6. Luồng Recovery Cốt Lõi

`RecoveryManager.recover()` là hàm trung tâm. Hàm này đọc toàn bộ WAL rồi chạy các bước:

1. `Analysis pass`
   - Tìm `redo_lsn` từ `END_CHECKPOINT` hợp lệ gần nhất.
   - Quét log từ `redo_lsn`.
   - Xác định trạng thái transaction: `LOSER`, `COMMITTED`, `ABORTED`, `IN_DOUBT`.

2. `Checkpoint failure detection`
   - Nếu có `BEGIN_CHECKPOINT` cuối cùng nhưng không có `END_CHECKPOINT` sau nó, hệ thống xem checkpoint đó đã bị crash giữa chừng.
   - Recovery bỏ qua checkpoint chưa hoàn tất và dùng checkpoint hợp lệ trước đó.

3. `Partial Redo`
   - Duyệt `UPDATE` từ `redo_lsn`.
   - Chỉ redo transaction đã `COMMIT`.
   - Ghi `after_image` vào snapshot.

4. `Global Undo`
   - Duyệt ngược WAL.
   - Undo transaction `LOSER` hoặc `ABORTED`.
   - Ghi `before_image` vào snapshot.

5. `In-doubt handling`
   - Transaction có `PREPARE`/`READY` nhưng chưa có `COMMIT`/`ABORT` được đánh dấu `IN_DOUBT`.
   - Nếu có coordinator resolver, recovery hỏi coordinator để biết quyết định cuối cùng là `COMMIT` hay `ABORT`.
   - Nếu `COMMIT` thì redo `after_image`; nếu `ABORT` thì undo `before_image`.

6. Hoàn tất
   - Tính `rto_seconds`.
   - Phát event `rto_complete`.
   - Trả về `RecoveryResult`.

## 7. Luồng Demo Realtime

Demo UI chạy theo pattern:

1. User chọn scenario hoặc config custom.
2. `api/routers/demo.py` sinh WAL/snapshot từ `data_gen`.
3. Backend stream từng WAL record ra WebSocket để UI hiển thị log đang chạy.
4. User bấm crash, backend dừng stream và đổi node status thành `CRASHED`.
5. User bấm recover, backend gọi `RecoveryManager.recover()`.
6. Recovery events được thu lại, sau đó broadcast có delay ngắn để UI hiển thị từng bước.
7. Node chuyển sang `CONSISTENT` khi recovery thành công.

Các event WebSocket được tạo trong `api/websocket/events.py`, ví dụ:

- `node_status`
- `crash`
- `log_entry`
- `recovery_pass`
- `recovery_record`
- `in_doubt_txn`
- `coordinator_query`
- `benchmark_progress`

## 8. Luồng Benchmark

Benchmark có hai chế độ:

- `generated`: mỗi run sinh WAL/snapshot riêng, sau đó recovery thật trên snapshot.
- `full_scale`: đọc dataset lớn có sẵn và scan cửa sổ WAL theo interval để ước lượng công việc recovery.

`benchmark_runner.py` chạy:

1. Duyệt danh sách checkpoint intervals.
2. Với mỗi interval, chạy `runs` lần.
3. Ghi raw JSON vào `results/raw/`.
4. Gọi `stats_analyzer.analyze_raw_dir()`.
5. Ghi summary CSV vào `results/summary.csv`.

`stats_analyzer.py` tính:

- mean RTO
- median RTO
- p99 RTO
- standard deviation
- I/O cost
- CPU cost
- communication cost
- theoretical RTO

## 9. Chất Lượng Và Giới Hạn

Những điểm hệ thống đã có:

- WAL binary record-aligned.
- Snapshot page read/write có offset rõ ràng.
- Recovery phases tách hàm riêng.
- `In-doubt 2PC transaction` có coordinator simulator.
- API/UI có realtime event stream.
- Benchmark có raw output và summary output.
- Test suite bảo vệ các đường chạy chính.

Giới hạn cần nêu rõ:

- Snapshot page chỉ là số nguyên 64-bit, không phải data page thật.
- Recovery đọc WAL vào memory bằng `list(iter_log_records(...))`, phù hợp simulator nhưng không tối ưu cho log rất lớn.
- Checkpoint metadata đơn giản, chưa lưu dirty page table hay active transaction table đầy đủ.
- Cost model dùng proxy để so sánh xu hướng, không thay thế đo đạc trên distributed database production.

## 10. Kết Luận

Kiến trúc hiện tại đáp ứng mục tiêu của đồ án: mô phỏng crash/recovery, minh họa WAL và checkpoint, đo RTO theo checkpoint interval, hiển thị realtime trên UI và tạo dữ liệu benchmark có thể phân tích lại.
