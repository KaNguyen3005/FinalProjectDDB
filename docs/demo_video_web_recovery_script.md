# Kịch Bản Quay Video Demo Web: WAL, Crash Và Recovery

Thời lượng mục tiêu: 4 đến 6 phút.

Mục tiêu video: chứng minh web demo có thể sinh WAL bằng `Apply Config`, hiển thị Live Log liên tục cho tới khi crash, rồi chạy recovery với các event `Analysis`, `Partial Redo`, `Global Undo`, `in-doubt`, và RTO.

## 1. Chuẩn Bị Trước Khi Quay

Chạy app:

```bash
python run.py
```

Mở trình duyệt:

- Demo: `http://127.0.0.1:8000/demo`
- Logs: `http://127.0.0.1:8000/logs`
- Benchmark: `http://127.0.0.1:8000/benchmark`

Checklist nhanh:

- Zoom trình duyệt khoảng 90% đến 100%.
- Để tab `/demo` là tab chính.
- Đảm bảo thấy các khu vực: cluster nodes, checkpoint interval, action buttons, Live Log Stream, Recovery Timeline, RTO stopwatch.
- Nếu Live Log đang có dữ liệu cũ, bấm `Apply Config` lại trước khi bắt đầu quay.
- Chuẩn bị sẵn danh sách scenario ở dropdown để demo nhanh các trường hợp dựng sẵn.

## 2. Mở Đầu Video

Thao tác:

- Đứng ở màn hình `/demo`.
- Chỉ vào cụm node và khu vực Live Log.

Lời thoại gợi ý:

> Đây là web demo mô phỏng disaster recovery cho hệ cơ sở dữ liệu dùng Write-Ahead Logging. Mục tiêu chính là quan sát checkpoint interval ảnh hưởng như thế nào tới Recovery Time Objective, hay RTO. Trên màn hình có cụm node, bộ điều khiển checkpoint, luồng WAL live log, timeline recovery, và đồng hồ đo RTO.

Điểm cần nhấn:

- WAL ghi lại các thay đổi trước khi dữ liệu được phục hồi.
- Crash sẽ dừng node được chọn.
- Recovery sẽ đọc WAL từ checkpoint phù hợp, sau đó redo hoặc undo record cần thiết.

## 3. Apply Config Và Quan Sát Live Log

Thao tác:

1. Chọn checkpoint interval ngắn, ví dụ `1m`.
2. Bấm `Apply Config`.
3. Chờ Live Log bắt đầu chạy.
4. Chỉ vào các dòng log có `LSN`, `TXN`, `START`, `UPDATE`, `COMMIT`, `ABORT`, `PREPARE`, hoặc `READY`.

Lời thoại gợi ý:

> Đầu tiên tôi bấm Apply Config để sinh workload mới. Mỗi lần apply, backend tạo một WAL file và snapshot mới cho lần chạy hiện tại. Live Log Stream đang phát các record WAL có liên quan tới vùng recovery sau checkpoint. Vì vậy các LSN ở đây sẽ đồng nhất với đoạn log mà recovery dùng sau khi crash.

> Mỗi dòng có LSN, transaction id, record type, page id, before image và after image. `UPDATE` thể hiện thay đổi trên page. `COMMIT` là transaction đã hoàn tất. `ABORT` hoặc transaction chưa kết thúc sẽ cần được undo. Nếu có `PREPARE` hoặc `READY` mà chưa có quyết định cuối, recovery sẽ coi đó là in-doubt transaction và hỏi coordinator.

Điểm cần nhấn:

- `Apply Config` không chỉ đổi UI, mà sinh dữ liệu WAL/snapshot mới.
- Live Log hiện chạy liên tục cho tới khi người dùng bấm crash.
- Live Log và Recovery Log đã được đồng bộ theo cùng vùng checkpoint/recovery.

## 4. Load Scenario Dựng Sẵn

Mục tiêu đoạn này: cho người xem thấy ngoài custom config, hệ thống còn có các kịch bản recovery được chuẩn bị sẵn để minh họa từng tình huống cụ thể.

Thao tác:

1. Mở dropdown scenario.
2. Chọn `Fast checkpoint: clean recovery`.
3. Bấm `Load Scenario`.
4. Quan sát Live Log và phần mô tả expected result.
5. Nếu có thời gian, lần lượt chọn thêm một hoặc hai scenario khác:
   - `Long checkpoint: heavy redo`
   - `Loser transactions: Global Undo`
   - `2PC in-doubt transaction`
   - `Checkpoint failure: BEGIN without END`

Lời thoại gợi ý:

> Ngoài chế độ Apply Config để sinh workload tùy chỉnh, web còn có các scenario dựng sẵn. Mỗi scenario được thiết kế để làm nổi bật một tình huống recovery riêng, giúp demo dễ hiểu và có thể lặp lại kết quả.

> Ví dụ `Fast checkpoint: clean recovery` tạo một WAL tail ngắn sau checkpoint, nên recovery nhanh và ít thao tác hơn. `Long checkpoint: heavy redo` tạo nhiều committed update sau checkpoint, nên phần Partial Redo rõ ràng hơn. `Loser transactions: Global Undo` có các transaction chưa hoàn tất hoặc abort, nên ta sẽ thấy recovery undo before image.

> Với `2PC in-doubt transaction`, một số transaction đã `PREPARE` hoặc `READY` nhưng chưa có `COMMIT` hoặc `ABORT`, nên recovery phải hỏi coordinator. Còn `Checkpoint failure` mô phỏng trường hợp có `BEGIN_CHECKPOINT` nhưng crash trước khi ghi `END_CHECKPOINT`, vì vậy recovery phải bỏ qua checkpoint chưa hoàn chỉnh và quay về checkpoint hợp lệ trước đó.

Điểm cần nhấn:

- `Apply Config` dùng cho workload tùy chỉnh.
- `Load Scenario` dùng cho các case recovery có chủ đích và dễ trình bày.
- Mỗi scenario đều sinh WAL/snapshot mới, nên Live Log và Recovery Timeline sẽ thay đổi theo scenario vừa chọn.
- Khi quay video ngắn, chỉ cần demo 1 scenario chính; khi quay video dài, có thể lướt nhanh 2 đến 3 scenario.

Gợi ý chọn scenario cho video:

- Video ngắn: dùng `2PC in-doubt transaction`, vì có đủ WAL, recovery, coordinator và in-doubt event.
- Video dễ hiểu nhất: dùng `Loser transactions: Global Undo`, vì người xem dễ thấy sự khác nhau giữa REDO và UNDO.
- Video nhấn mạnh checkpoint: dùng `Checkpoint failure` hoặc `Long checkpoint: heavy redo`.

## 5. Crash Node

Thao tác:

1. Chọn node muốn crash, mặc định có thể để `A`.
2. Bấm `Crash Selected Node`.
3. Chỉ vào trạng thái node chuyển sang `CRASHED`.
4. Chỉ vào stopwatch bắt đầu chạy.
5. Chỉ vào Live Log đã dừng tại thời điểm crash.

Lời thoại gợi ý:

> Bây giờ tôi giả lập sự cố bằng cách crash Node A. Khi crash xảy ra, live WAL stream dừng lại, trạng thái node chuyển sang crashed, và đồng hồ RTO bắt đầu tính. Từ thời điểm này, hệ thống cần dùng WAL để đưa node về trạng thái nhất quán.

Điểm cần nhấn:

- Crash là mốc bắt đầu đo RTO.
- Log stream dừng đúng lúc crash để mô phỏng hệ thống bị gián đoạn.
- Các record đã thấy trên Live Log là cơ sở để đối chiếu với recovery event.

## 6. Recover Và Giải Thích Các Pha

Thao tác:

1. Bấm `Recover`.
2. Khi timeline chạy, chỉ vào các pha:
   - `Analysis`
   - `Partial Redo`
   - `Global Undo`
3. Chỉ vào các dòng `[RECOVERY REDO]`, `[RECOVERY UNDO]`, `[IN-DOUBT]`, `[COORDINATOR]`.
4. Chỉ vào node chuyển về `CONSISTENT`.
5. Chỉ vào RTO cuối cùng.

Lời thoại gợi ý:

> Khi tôi bấm Recover, backend chạy recovery manager trên WAL của run hiện tại. Run này có thể đến từ Apply Config hoặc từ scenario dựng sẵn vừa load. Pha đầu tiên là Analysis, dùng để tìm checkpoint hợp lệ gần nhất và phân loại transaction. Sau đó Partial Redo phát lại các update của transaction đã commit để đảm bảo durability. Tiếp theo Global Undo rollback các transaction abort hoặc transaction đang dang dở để đảm bảo atomicity.

> Các dòng `[RECOVERY REDO]` và `[RECOVERY UNDO]` đang dùng cùng LSN với WAL stream. Ví dụ REDO dùng after image, còn UNDO dùng before image. Nếu xuất hiện in-doubt transaction, hệ thống sẽ hỏi coordinator. Nếu coordinator không có quyết định cuối, transaction được giữ ở trạng thái unknown/in-doubt thay vì tự ý commit hoặc abort.

> Khi recovery hoàn tất, node trở về trạng thái consistent và đồng hồ RTO dừng. Giá trị này là thời gian phục hồi quan sát được từ lúc crash tới lúc hệ thống nhất quán trở lại.

Điểm cần nhấn:

- `Analysis` xác định điểm bắt đầu recovery.
- `Partial Redo` bảo vệ committed transaction.
- `Global Undo` bảo vệ atomicity cho transaction chưa hoàn tất.
- `In-doubt` mô phỏng tình huống distributed transaction cần coordinator.
- Recovery log không phải log khác; nó là event diễn giải hành động trên WAL record.

## 7. Demo Nhanh Một Scenario Khác Nếu Còn Thời Gian

Đoạn này là tùy chọn. Chỉ dùng nếu video cần chứng minh nhiều case.

Thao tác:

1. Quay lại dropdown scenario.
2. Chọn `Checkpoint failure: BEGIN without END`.
3. Bấm `Load Scenario`.
4. Bấm `Crash Selected Node`.
5. Bấm `Recover`.
6. Chỉ vào checkpoint failure banner hoặc timeline message.

Lời thoại gợi ý:

> Tôi load thêm scenario checkpoint failure để cho thấy recovery không tin mọi checkpoint một cách mù quáng. Ở đây hệ thống có `BEGIN_CHECKPOINT` nhưng thiếu `END_CHECKPOINT`, nghĩa là checkpoint chưa hoàn chỉnh. Khi recover, hệ thống phát hiện lỗi này và fallback về checkpoint hợp lệ trước đó.

Nếu muốn demo 2PC thay vì checkpoint failure:

1. Chọn `2PC in-doubt transaction`.
2. Bấm `Load Scenario`.
3. Crash và Recover.
4. Chỉ vào `[IN-DOUBT]` và `[COORDINATOR]`.

Lời thoại thay thế:

> Scenario này minh họa distributed transaction. Một số transaction đã sẵn sàng commit nhưng chưa có quyết định cuối. Recovery không tự ý đoán, mà hỏi coordinator để lấy quyết định commit hoặc abort.

## 8. Đối Chiếu Với Trang Logs

Thao tác:

1. Mở tab `/logs`.
2. Chỉ vào bảng WAL record.
3. Lọc hoặc phân trang nếu cần.
4. Quay lại `/demo`.

Lời thoại gợi ý:

> Trang Logs dùng để inspect WAL ở dạng bảng. Nếu cần kiểm tra chi tiết, ta có thể đối chiếu record type, LSN, transaction id và page id tại đây. Còn màn hình Demo tập trung vào luồng sự kiện trực quan: WAL chạy, crash, recovery, và RTO.

Điểm cần nhấn:

- `/logs` là màn hình kiểm chứng dữ liệu WAL.
- `/demo` là màn hình trình diễn luồng recovery end-to-end.

## 9. Chuyển Sang Benchmark

Thao tác:

1. Mở tab `/benchmark`.
2. Chỉ vào biểu đồ hoặc bảng kết quả.
3. Nhắc lại biến độc lập và metric chính.

Lời thoại gợi ý:

> Sau phần demo trực tiếp, màn hình Benchmark cho thấy tác động của checkpoint interval lên RTO. Biến độc lập là checkpoint interval, còn metric chính là recovery time. Về trực giác, checkpoint càng xa thì recovery càng phải scan và xử lý nhiều WAL record hơn, nên RTO có xu hướng tăng.

Điểm cần nhấn:

- Independent variable: checkpoint interval.
- Dependent metric: RTO.
- Có thể so sánh mean, median, P99 và cost breakdown nếu video còn thời gian.

## 10. Kết Luận Video

Thao tác:

- Quay về `/demo`, để node ở trạng thái `CONSISTENT`.
- Chỉ vào RTO cuối và Live Log có recovery events.

Lời thoại gợi ý:

> Tóm lại, demo này cho thấy toàn bộ vòng đời disaster recovery: sinh WAL bằng Apply Config hoặc load scenario dựng sẵn, quan sát live log, crash node, chạy recovery, redo committed work, undo incomplete work, xử lý in-doubt transaction, phát hiện checkpoint failure nếu có, và đo RTO. Điểm quan trọng là Live Log và Recovery Log đã được đồng bộ theo cùng vùng WAL sau checkpoint, nên có thể dùng LSN để đối chiếu trực tiếp giữa record gốc và hành động recovery.

## 11. Nhịp Quay Gợi Ý

- 0:00-0:30: Giới thiệu màn hình và mục tiêu.
- 0:30-1:20: Apply Config và giải thích Live Log.
- 1:20-2:10: Load Scenario dựng sẵn và giải thích ý nghĩa từng scenario.
- 2:10-2:50: Crash node và giải thích RTO bắt đầu.
- 2:50-4:30: Recover, giải thích Analysis, Redo, Undo, In-doubt.
- 4:30-5:20: Tùy chọn demo thêm checkpoint failure hoặc 2PC.
- 5:20-6:00: Đối chiếu `/logs`, chuyển `/benchmark`, kết luận.

## 12. Câu Chốt Ngắn Nếu Cần Video Dưới 3 Phút

> Demo này mô phỏng một hệ thống dùng WAL để phục hồi sau crash. Tôi có thể sinh workload bằng Apply Config hoặc load các scenario dựng sẵn như Global Undo, 2PC in-doubt, và checkpoint failure. Sau đó tôi quan sát WAL chạy liên tục, crash node, rồi recover. Recovery bắt đầu từ checkpoint phù hợp, redo transaction đã commit, undo transaction chưa hoàn tất, xử lý in-doubt nếu có, và cuối cùng đo RTO. Đây là cơ sở để so sánh checkpoint interval ảnh hưởng thế nào tới thời gian phục hồi.
