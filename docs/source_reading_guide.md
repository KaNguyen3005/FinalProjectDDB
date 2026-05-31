# Huong dan doc source code

Tai lieu nay huong dan doc source theo luong logic, khong doc theo thu tu alphabet. Nen doc theo cac vong: vong tong quan, vong recovery, vong API/UI, vong benchmark.

## 1. Vong 15 phut dau

Bat dau voi cac file nay:

1. `README.md`
2. `run.py`
3. `api/app.py`
4. `src/main.py`

Sau vong nay, ban can nam duoc:

- App chay bang `python run.py`.
- FastAPI app nam o `api.app:app`.
- CLI recovery nam o `src/main.py`.
- Project co 3 man hinh UI: demo, benchmark, logs.
- Core recovery khong nam trong API ma nam trong `src/recovery/recovery_manager.py`.

## 2. Duong doc quan trong nhat: WAL va recovery

Doc theo thu tu:

1. `src/log/log_record.py`
2. `src/storage.py`
3. `src/checkpoint/checkpoint_manager.py`
4. `data_gen/generate_logs.py`
5. `src/recovery/recovery_manager.py`

### 2.1. `src/log/log_record.py`

Day la file nen doc dau tien neu muon hieu recovery.

Can chu y:

- `RecordType`: cac loai record trong WAL.
- `LogRecord.STRUCT`: binary format cua moi record.
- `lsn`: so thu tu log, tang dan.
- `before_image`: gia tri de UNDO.
- `after_image`: gia tri de REDO.
- `redo_lsn`: diem recovery bat dau sau checkpoint.
- `WalWriter.append()`: moi lan append tao mot LSN moi.
- `iter_log_records()`: doc WAL thanh cac `LogRecord`.

Neu chua hieu `before_image` va `after_image`, dung lai o day. Hai field nay la chia khoa cua REDO/UNDO.

### 2.2. `src/storage.py`

File nay rat nho nhung quan trong. No cho thay snapshot duoc mo phong nhu mot mang page trong file nhi phan.

Can chu y:

- Moi page la mot so nguyen 64-bit.
- `read_page()` doc page theo offset.
- `write_page()` ghi gia tri moi vao page.
- Recovery that su thay doi snapshot bang `write_page()`.

### 2.3. `src/checkpoint/checkpoint_manager.py`

Checkpoint trong simulator la cap record:

- BEGIN_CHECKPOINT
- END_CHECKPOINT

`END_CHECKPOINT.redo_lsn` cho recovery biet nen bat dau scan lai tu dau.

Doc them tham so `fail_after_begin`: no tao tinh huong crash sau BEGIN_CHECKPOINT nhung truoc END_CHECKPOINT.

### 2.4. `data_gen/generate_logs.py`

File nay tra loi cau hoi: WAL va snapshot duoc tao ra nhu the nao?

Can chu y:

- Generator tao snapshot moi.
- Moi transaction ghi START, UPDATE, roi COMMIT/ABORT/PREPARE/READY.
- Mot so update duoc ghi ngay vao snapshot de recovery co viec phai undo.
- Checkpoint duoc ghi dinh ky theo `checkpoint_every`.

### 2.5. `src/recovery/recovery_manager.py`

Day la file trung tam cua project.

Doc `recover()` truoc, sau do moi doc cac ham private theo dung thu tu no goi:

1. `_analysis_pass()`
2. `_detect_checkpoint_failure()`
3. `_partial_redo()`
4. `_global_undo()`
5. `_handle_in_doubt()`
6. `_resolve_in_doubt()`

Khi doc, hay tu ve bang transaction state:

```text
START        -> LOSER
PREPARE      -> IN_DOUBT
READY        -> IN_DOUBT neu chua co state
COMMIT       -> COMMITTED
ABORT        -> ABORTED
```

Quy tac phuc hoi:

- COMMITTED: redo UPDATE bang `after_image`.
- LOSER/ABORTED: undo UPDATE bang `before_image`.
- IN_DOUBT: khong tu quyet, hoi coordinator neu co.

## 3. Duong doc demo realtime

Doc theo thu tu:

1. `data_gen/demo_scenarios.py`
2. `api/state.py`
3. `api/routers/demo.py`
4. `api/websocket/events.py`
5. `api/websocket/manager.py`
6. `ui/js/ws-client.js`
7. `ui/js/demo.js`
8. `ui/demo.html`

### 3.1. `data_gen/demo_scenarios.py`

File nay tao cac WAL co chu dich:

- checkpoint nhanh, recovery sach
- checkpoint dai, redo nhieu
- loser transaction can Global Undo
- 2PC in-doubt transaction
- checkpoint failure

Nen doc `SCENARIOS` truoc, sau do doc `generate_demo_scenario()`, cuoi cung doc `_write_plan()`.

### 3.2. `api/routers/demo.py`

File nay la bo dieu khien demo.

Endpoint can nam:

- `GET /api/demo/status`
- `GET /api/demo/scenarios`
- `POST /api/demo/scenario`
- `POST /api/demo/config`
- `POST /api/demo/crash`
- `POST /api/demo/recover`
- `POST /api/demo/recover-interrupted`
- `GET /api/demo/recent-log`

Luong chay:

1. Load scenario.
2. Restart log stream.
3. Broadcast WAL entries.
4. Crash node.
5. Run recovery.
6. Broadcast recovery events theo tung buoc.

### 3.3. WebSocket files

`api/websocket/events.py` tao payload dict chuan cho UI.

`api/websocket/manager.py` giu danh sach WebSocket connection va broadcast event cho tat ca client.

`ui/js/ws-client.js` la client dung chung de browser nhan event.

## 4. Duong doc benchmark

Doc theo thu tu:

1. `benchmark/benchmark_runner.py`
2. `benchmark/stats_analyzer.py`
3. `benchmark/cost_model.py`
4. `benchmark/chart_generator.py`
5. `api/routers/benchmark.py`
6. `ui/js/benchmark.js`
7. `ui/benchmark.html`

### 4.1. `benchmark/benchmark_runner.py`

Doc cac ham:

- `run_single_benchmark()`: sinh data moi va recovery that.
- `run_single_full_scale_benchmark()`: scan dataset lon.
- `_scan_full_scale_window()`: dem committed/aborted/in-doubt trong cua so log.
- `write_raw_result()`: ghi raw JSON.
- `run_benchmark_matrix()`: chay toan bo intervals x runs.

Can hieu cong thuc seed:

```text
run_seed = seed + interval * 10000 + run
```

Cong thuc nay giup moi interval/run co data rieng nhung van tai lap duoc.

### 4.2. `benchmark/stats_analyzer.py`

File nay gom raw JSON theo `interval_min`, tinh thong ke va ghi `summary.csv`.

Neu chi can hieu output benchmark, doc:

- `SUMMARY_FIELDS`
- `summarize_results()`
- `write_summary_csv()`

### 4.3. `api/routers/benchmark.py`

File nay boc benchmark CLI thanh API async. Vi benchmark co the ton thoi gian, API chay no trong background task va broadcast tien do qua WebSocket.

## 5. Duong doc log inspector

Doc theo thu tu:

1. `api/routers/logs.py`
2. `src/log/log_record.py`
3. `ui/js/logs.js`
4. `ui/logs.html`

`GET /api/logs/records` tra ve WAL records co phan trang.

`GET /api/logs/stream` la Server-Sent Events stream doc record moi.

## 6. Lenh nen chay khi doc

Chay app:

```bash
python run.py
```

Chay CLI recovery:

```bash
python src/main.py --crash-and-recover --interval 5 --verbose-events
```

Chay benchmark nho:

```bash
python benchmark/benchmark_runner.py --intervals 1 5 --runs 2 --transactions 50 --pages 30
```

Chay test:

```bash
pytest tests/ -v
```

## 7. Cac cau hoi nen tu tra loi khi doc

Khi doc xong `src/log/log_record.py`:

- Mot WAL record co nhung field nao?
- LSN tang nhu the nao?
- Khi nao record co `page_id`?

Khi doc xong `src/recovery/recovery_manager.py`:

- Tai sao recovery bat dau tu `redo_lsn`?
- Transaction nao duoc REDO?
- Transaction nao bi UNDO?
- Transaction IN_DOUBT khac LOSER o dau?

Khi doc xong `api/routers/demo.py`:

- Khi bam Crash, stream log dung o dau?
- Khi Recover, recovery event duoc broadcast nhu the nao?
- Tai sao co `recover-interrupted`?

Khi doc xong `benchmark/benchmark_runner.py`:

- `generated` mode va `full_scale` mode khac nhau the nao?
- Raw JSON duoc ghi o dau?
- Summary CSV duoc tao tu dau?

## 8. File can doc sau cung

Doc sau khi da hieu luong chinh:

- `tests/`: de xem expectation cua he thong.
- `docs/design_document.md`: de doi chieu thiet ke ban dau.
- `docs/analysis_report.md`: de xem ket qua va cach dien giai benchmark.
- `roadmap.md`: de xem yeu cau goc cua project.

## 9. Ban do logic ngan gon

```text
run.py
  -> api/app.py
      -> api/routers/demo.py
          -> data_gen/demo_scenarios.py
          -> src/recovery/recovery_manager.py
          -> api/websocket/manager.py

src/main.py
  -> data_gen/generate_logs.py
  -> src/recovery/recovery_manager.py

benchmark/benchmark_runner.py
  -> data_gen/generate_logs.py
  -> src/recovery/recovery_manager.py
  -> benchmark/stats_analyzer.py
```

Neu chi co thoi gian doc 3 file, hay doc:

1. `src/log/log_record.py`
2. `src/recovery/recovery_manager.py`
3. `benchmark/benchmark_runner.py`
