# Bao cao kien truc he thong

## 1. Tong quan

Du an nay la mot simulator va benchmark cho Recovery Time Objective (RTO) trong mot he thong database phan tan gia lap. Muc tieu chinh la quan sat checkpoint interval anh huong nhu the nao den thoi gian phuc hoi sau crash.

He thong gom 6 lop chinh:

- Core recovery engine trong `src/`
- FastAPI backend trong `api/`
- WebSocket event stream cho UI realtime
- Browser UI trong `ui/`
- Benchmark va thong ke trong `benchmark/`
- Data generation va demo scenario trong `data_gen/`

Luon can phan biet ro: day la simulator cho muc dich hoc thuat/benchmark, khong phai distributed database production.

## 2. Kien truc thu muc

`run.py` la entry point de khoi dong web app FastAPI.

`src/` chua logic cot loi:

- `src/log/log_record.py`: dinh nghia binary WAL record, record type, LSN va writer/reader.
- `src/storage.py`: thao tac snapshot page don gian bang file nhi phan.
- `src/checkpoint/checkpoint_manager.py`: ghi BEGIN_CHECKPOINT va END_CHECKPOINT.
- `src/recovery/recovery_manager.py`: thuat toan recovery gom Analysis, Partial Redo, Global Undo va xu ly transaction in-doubt.
- `src/coordinator/coordinator.py`: coordinator simulator cho 2PC decision.
- `src/crash/`: tien ich crash/recovery timing.
- `src/integrity/`: checksum snapshot.

`api/` chua backend:

- `api/app.py`: tao FastAPI app, gan REST router, static UI va WebSocket.
- `api/state.py`: trang thai runtime cua demo va benchmark.
- `api/routers/demo.py`: API dieu khien demo scenario, crash, recover.
- `api/routers/benchmark.py`: API chay benchmark nen va lay ket qua.
- `api/routers/logs.py`: API xem WAL records.
- `api/websocket/events.py`: factory tao event payload.
- `api/websocket/manager.py`: quan ly WebSocket clients.

`benchmark/` chua pipeline benchmark:

- `benchmark_runner.py`: chay ma tran interval x run.
- `stats_analyzer.py`: tong hop raw JSON thanh summary CSV.
- `cost_model.py`: uoc luong chi phi I/O, CPU, communication va RTO ly thuyet.
- `chart_generator.py`: sinh chart tu summary.

`data_gen/` chua bo sinh du lieu:

- `generate_logs.py`: sinh WAL va snapshot ngau nhien co tai lap bang seed.
- `demo_scenarios.py`: sinh cac scenario co chu dich cho UI demo.
- `generate_full_scale_dataset.py`: sinh dataset lon.
- `generate_snapshot.py`: tao snapshot rieng.

`ui/` chua frontend tinh bang HTML/CSS/vanilla JS:

- `demo.html`: dashboard demo crash/recovery.
- `benchmark.html`: dashboard benchmark.
- `logs.html`: WAL inspector.
- `ui/js/ws-client.js`: WebSocket client dung chung.
- `ui/js/demo.js`, `benchmark.js`, `logs.js`: logic tung man hinh.

`tests/` la pytest suite bao ve format WAL, recovery, API, benchmark va data generation.

## 3. Kien truc runtime

Khi chay:

```bash
python run.py
```

`run.py` goi `uvicorn.run("api.app:app")`. FastAPI app duoc tao trong `api/app.py` bang `create_app()`.

App gan cac route:

- `/api/health`: health check.
- `/api/demo/*`: demo scenario, crash va recover.
- `/api/benchmark/*`: benchmark run, status, results.
- `/api/logs/*`: doc va stream WAL records.
- `/ws/events`: WebSocket event stream.
- `/demo`, `/benchmark`, `/logs`: tra ve UI HTML.

UI goi REST API de bat dau hanh dong, sau do lang nghe WebSocket de hien thi node status, WAL log entries, recovery pass va benchmark progress.

## 4. Mo hinh du lieu

Snapshot la file nhi phan gom nhieu page. Trong simulator, moi page chi la mot so nguyen 64-bit. `src/storage.py` doc/ghi page bang offset:

```text
offset = page_id * 8
```

WAL la file nhi phan record-aligned. Moi record co kich thuoc co dinh `LogRecord.SIZE`.

Moi `LogRecord` gom cac thong tin quan trong:

- `record_type`: START, UPDATE, COMMIT, ABORT, BEGIN_CHECKPOINT, END_CHECKPOINT, PREPARE, READY.
- `lsn`: log sequence number tang dan.
- `txn_id`: transaction id.
- `page_id`: page bi sua, chi co y nghia voi UPDATE.
- `before_image`: gia tri truoc update, dung cho UNDO.
- `after_image`: gia tri sau update, dung cho REDO.
- `redo_lsn`: diem bat dau redo ghi trong END_CHECKPOINT.
- `node_id`: node phat sinh record.
- `timestamp`: thoi diem tao record.

## 5. Luong sinh du lieu

`data_gen/generate_logs.py` tao snapshot moi, xoa WAL cu, roi sinh transaction:

1. Ghi checkpoint ban dau.
2. Voi moi transaction: ghi START.
3. Ghi 1 den 3 UPDATE.
4. Mot so update duoc flush vao snapshot de tao tinh huong can UNDO.
5. Ket thuc bang COMMIT, ABORT hoac PREPARE/READY.
6. Dinh ky ghi checkpoint theo `checkpoint_every`.

`data_gen/demo_scenarios.py` khac voi generator ngau nhien: no tao WAL theo kich ban co chu dich de minh hoa tung truong hop recovery.

## 6. Luong recovery cot loi

`RecoveryManager.recover()` la ham trung tam. No doc toan bo WAL roi chay cac buoc:

1. Analysis pass
   - Tim `redo_lsn` tu END_CHECKPOINT hop le gan nhat.
   - Quet log tu `redo_lsn`.
   - Xac dinh trang thai transaction: LOSER, COMMITTED, ABORTED, IN_DOUBT.

2. Checkpoint failure detection
   - Neu co BEGIN_CHECKPOINT cuoi cung ma khong co END_CHECKPOINT sau no, he thong xem checkpoint do bi crash giua chung.
   - Recovery bo qua checkpoint chua hoan tat va dung checkpoint hop le truoc do.

3. Partial Redo
   - Duyet UPDATE tu `redo_lsn`.
   - Chi redo transaction da COMMIT.
   - Ghi `after_image` vao snapshot.

4. Global Undo
   - Duyet nguoc WAL.
   - Undo transaction LOSER hoac ABORTED.
   - Ghi `before_image` vao snapshot.

5. In-doubt handling
   - Transaction PREPARE/READY nhung chua COMMIT/ABORT duoc danh dau IN_DOUBT.
   - Neu co coordinator resolver, recovery hoi coordinator de biet COMMIT hay ABORT.
   - Neu COMMIT thi redo `after_image`; neu ABORT thi undo `before_image`.

6. Hoan tat
   - Tinh `rto_seconds`.
   - Phat event `rto_complete`.
   - Tra ve `RecoveryResult`.

## 7. Luong demo realtime

Demo UI chay theo pattern:

1. User chon scenario hoac config custom.
2. `api/routers/demo.py` sinh WAL/snapshot tu `data_gen`.
3. Backend stream tung WAL record ra WebSocket de UI hien thi log dang chay.
4. User bam crash, backend dung stream va doi node status thanh CRASHED.
5. User bam recover, backend goi `RecoveryManager.recover()`.
6. Recovery events duoc thu lai, sau do broadcast co delay ngan de UI hien thi tung buoc.
7. Node chuyen sang CONSISTENT khi recovery thanh cong.

Cac event WebSocket duoc tao trong `api/websocket/events.py`, vi du:

- `node_status`
- `crash`
- `log_entry`
- `recovery_pass`
- `recovery_record`
- `in_doubt_txn`
- `coordinator_query`
- `benchmark_progress`

## 8. Luong benchmark

Benchmark co hai che do:

- `generated`: moi run sinh WAL/snapshot rieng, sau do recovery that tren snapshot.
- `full_scale`: doc dataset lon co san va scan cua so WAL theo interval de uoc luong cong viec recovery.

`benchmark_runner.py` chay:

1. Duyet danh sach checkpoint intervals.
2. Voi moi interval, chay `runs` lan.
3. Ghi raw JSON vao `results/raw/`.
4. Goi `stats_analyzer.analyze_raw_dir()`.
5. Ghi summary CSV vao `results/summary.csv`.

`stats_analyzer.py` tinh:

- mean RTO
- median RTO
- p99 RTO
- standard deviation
- I/O cost
- CPU cost
- communication cost
- theoretical RTO

## 9. Chat luong va gioi han

Nhung diem he thong da co:

- WAL binary record-aligned.
- Snapshot page read/write co offset ro rang.
- Recovery phases tach ham rieng.
- In-doubt 2PC transaction co coordinator simulator.
- API/UI co realtime event stream.
- Benchmark co raw output va summary output.
- Test suite bao ve cac duong chay chinh.

Gioi han can neu trong bao cao:

- Snapshot page chi la so nguyen 64-bit, khong phai data page that.
- Recovery doc WAL vao memory bang `list(iter_log_records(...))`, phu hop simulator nhung khong toi uu cho log rat lon.
- Checkpoint metadata don gian, chua luu dirty page table hay active transaction table day du.
- Full-scale benchmark mode khong apply snapshot recovery day du; no mo phong scan window va dem chi phi.
- WebSocket event stream phuc vu visualization, khong phai event bus production.

## 10. Ket luan kien truc

Kien truc hien tai phu hop muc tieu project: minh hoa anh huong cua checkpoint interval den RTO, dong thoi cho thay cac thanh phan quan trong cua disaster recovery: WAL, checkpoint, redo, undo, in-doubt 2PC va benchmark/statistics.

Neu mo rong thanh simulator nang cao hon, cac huong nen uu tien la:

- Them checkpoint metadata gan voi dirty page table va transaction table.
- Doc WAL streaming thay vi load toan bo.
- Them nhieu node co log rieng va coordinator protocol ro hon.
- Them failure model phuc tap hon: network partition, coordinator crash, partial disk write.
- Them invariant checker sau recovery.
