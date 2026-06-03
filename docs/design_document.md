# Tài Liệu Thiết Kế: RTO Disaster Recovery Benchmark

## 1. Phạm Vi

Dự án đo `checkpoint frequency` ảnh hưởng như thế nào đến `Recovery Time Objective` (`RTO`) của một distributed database node sau crash. Phần triển khai được giữ đủ nhỏ để chạy trên laptop, nhưng vẫn bảo toàn các khái niệm recovery quan trọng trong roadmap:

- `Write-Ahead Log` (`WAL`) có `before_image` và `after_image`.
- Marker `BEGIN_CHECKPOINT` và `END_CHECKPOINT`.
- Các phase recovery: `Analysis`, `Partial Redo`, `Global Undo`.
- Record `2PC PREPARE`/`READY` và phát hiện `in-doubt transaction`.
- Ma trận benchmark có input kiểm soát được.
- Browser UI để demo crash và recovery realtime.

## 2. Kiến Trúc

```text
Browser UI
  /demo        dashboard crash và recovery realtime
  /benchmark   chart benchmark và bảng summary
  /logs        WAL inspector có phân trang
      |
      | REST control/results + WebSocket events
      v
FastAPI backend
  api/routers/demo.py       crash, recover, configure demo
  api/routers/benchmark.py  background benchmark run và results
  api/routers/logs.py       WAL record inspection
  api/websocket/*           event fan-out
      |
      v
Core engine
  src/log/                  fixed-size binary WAL records
  src/storage.py            binary snapshot pages
  src/checkpoint/           checkpoint markers
  src/recovery/             Analysis, Partial Redo, Global Undo
  src/crash/                crash injection và RTO timer
      |
      v
Generated data and results
  data/                     generated WAL và snapshots
  results/raw/              per-run benchmark JSON
  results/summary.csv       aggregate statistics
  results/charts/           generated SVG report charts
```

Thiết kế tách rõ phần core và phần trình diễn:

- Core engine không phụ thuộc FastAPI hay UI.
- API chỉ điều phối action, stream event và trả result.
- UI hiển thị trạng thái realtime nhưng không giữ logic recovery.
- Benchmark dùng lại recovery engine để đo RTO.

## 3. Recovery Flow

`RecoveryManager` ánh xạ trực tiếp với thuật ngữ trong roadmap.

| Bước | Implementation | Mapping lý thuyết | Mục đích |
|---|---|---|---|
| 1 | Tìm `redo_lsn` của `END_CHECKPOINT` mới nhất | Checkpointing | Tránh scan toàn bộ log sau mỗi crash. |
| 2 | `Analysis pass` xây transaction states | WAL recovery | Phân loại transaction thành `COMMITTED`, `ABORTED`, `LOSER`, `IN_DOUBT`. |
| 3 | `Partial Redo` áp dụng lại `after_image` của committed `UPDATE` | Partial Redo | Đảm bảo durability cho committed updates sau checkpoint. |
| 4 | `Global Undo` khôi phục `before_image` cho loser hoặc aborted transactions | Global Undo | Đảm bảo atomicity cho công việc chưa hoàn tất. |
| 5 | `PREPARE`/`READY` không có quyết định cuối trở thành `IN_DOUBT` | Site failure và 2PC | Không tự ý undo participant có thể đã commit ở mức global. |

Implementation dùng cấu trúc pass giống ARIES ở mức ý tưởng, nhưng event name, UI label và thuật ngữ báo cáo vẫn theo `Partial Redo` và `Global Undo` trong roadmap.

## 4. WAL Record Model

`src/log/log_record.py` lưu fixed-size binary records. Các record type được hỗ trợ:

| Type | Ý nghĩa |
|---|---|
| `START` | Transaction bắt đầu. |
| `UPDATE` | Chứa `page_id`, `before_image` và `after_image`. |
| `COMMIT` | Transaction đã commit; recovery redo `after_image`. |
| `ABORT` | Transaction đã abort; recovery undo `before_image`. |
| `BEGIN_CHECKPOINT` | Checkpoint bắt đầu. |
| `END_CHECKPOINT` | Dirty pages đã được flush; recovery có thể bắt đầu từ `redo_lsn`. |
| `PREPARE` | Quyết định prepare của `2PC` đã được log. |
| `READY` | Participant vote yes và đang chờ quyết định cuối. |

WAL được thiết kế record-aligned để reader có thể đọc tuần tự và phát hiện record không hợp lệ.

## 5. Snapshot Model

Snapshot được mô phỏng bằng file nhị phân. Mỗi page là một số nguyên 64-bit, và offset được tính bằng:

```text
offset = page_id * 8
```

Mô hình này đơn giản hơn database page thật, nhưng đủ để minh họa hiệu ứng của `redo` và `undo`:

- `redo` ghi `after_image` vào page.
- `undo` ghi `before_image` vào page.

## 6. Crash Injection Methodology

Demo path tạo WAL và snapshot có thể tái lập cho checkpoint interval hoặc scenario được chọn. Khi crash xảy ra, Node A được đánh dấu failed, timestamp crash được ghi lại và UI stopwatch bắt đầu.

Recovery gọi `RecoveryManager.recover()` trên log và snapshot hiện tại. Đo RTO bắt đầu ngay trước khi recovery work chạy và dừng sau khi snapshot nhất quán, result được tạo và event hoàn tất được phát ra.

## 7. Variable Control

| Variable | Control strategy |
|---|---|
| `Checkpoint interval` | Independent variable: 1, 2, 5, 10, 20, 30 phút trong full benchmark. |
| Randomness | Seeded generator; benchmark runner suy ra per-run seed từ base seed, interval và run id. |
| Transaction count | Cố định theo `--transactions`. |
| Snapshot size | Cố định theo `--pages`. |
| Transaction rate cho cost model | Cố định bằng `--txn-rate`, mặc định 10 transactions/second. |
| Hardware và process overhead | Tất cả interval chạy qua cùng Python engine và benchmark runner. |
| Statistical repetition | Full target là 10 runs mỗi interval; smoke baseline có thể dùng ít runs hơn. |

## 8. Kiến Trúc UI

UI là HTML/CSS/JavaScript tĩnh được serve bởi FastAPI. REST endpoints kích hoạt action và lấy persisted results, còn `/ws/events` stream live events cho demo dashboard.

| Page | Hành vi chính |
|---|---|
| `/demo` | Configure interval, crash Node A, recover, stream log entries và recovery phases. |
| `/benchmark` | Launch benchmark nhỏ, hiển thị progress, render RTO và cost charts. |
| `/logs` | Inspect WAL records với node filter và pagination. |

UI tránh giấu server-side state trong browser. Khi page load, UI gọi status/result endpoints trước, sau đó WebSocket events cập nhật trạng thái hiển thị.

## 9. Reproducibility

```bash
python benchmark/benchmark_runner.py --intervals 1 2 5 10 20 30 --runs 10 --seed 42
python benchmark/chart_generator.py
python -m pytest tests/ -v
```

Report charts được regenerate từ `results/summary.csv`, vì vậy phần analysis có thể tái lập sau mỗi benchmark run mới.
