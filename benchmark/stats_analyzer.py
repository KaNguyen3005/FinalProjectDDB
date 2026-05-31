from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Iterable

from benchmark.cost_model import estimate_recovery_cost


# Danh sách các cột sẽ được ghi ra file summary CSV.
#
# File CSV sau khi phân tích benchmark sẽ có các cột:
# - interval_min: checkpoint interval, tính theo phút.
# - mean_s: thời gian recovery trung bình.
# - median_s: trung vị thời gian recovery.
# - p99_s: percentile 99%, tức gần worst-case recovery time.
# - std_s: độ lệch chuẩn của recovery time.
# - io_cost: chi phí I/O lý thuyết.
# - cpu_cost: chi phí CPU lý thuyết.
# - comm_cost: chi phí communication lý thuyết.
# - theory_rto_s: RTO lý thuyết tính từ mô hình chi phí.
SUMMARY_FIELDS = [
    "interval_min",
    "mean_s",
    "median_s",
    "p99_s",
    "std_s",
    "io_cost",
    "cpu_cost",
    "comm_cost",
    "theory_rto_s",
]


def percentile(values: list[float], pct: float) -> float:
    """
    Tính percentile cho một danh sách số.

    Ví dụ:
    - pct = 0.5  tương đương median / P50.
    - pct = 0.9  tương đương P90.
    - pct = 0.99 tương đương P99.

    Hàm này dùng nội suy tuyến tính nếu vị trí percentile
    nằm giữa hai phần tử.

    Ví dụ:
        values = [1, 2, 3, 4]
        pct = 0.5

        rank = (4 - 1) * 0.5 = 1.5

        lower = 1
        upper = 2

        kết quả = values[1] * 0.5 + values[2] * 0.5
                = 2 * 0.5 + 3 * 0.5
                = 2.5
    """

    # Không thể tính percentile nếu danh sách rỗng.
    if not values:
        raise ValueError("cannot compute percentile of empty values")

    # Sắp xếp các giá trị tăng dần.
    # Percentile luôn cần dữ liệu đã được sort.
    ordered = sorted(values)

    # Nếu chỉ có một giá trị, percentile nào cũng chính là giá trị đó.
    if len(ordered) == 1:
        return ordered[0]

    # Tính vị trí lý thuyết của percentile trong mảng đã sort.
    #
    # Ví dụ len = 100, pct = 0.99:
    #   rank = 99 * 0.99 = 98.01
    #
    # Vị trí này có thể không phải số nguyên,
    # nên cần nội suy giữa lower và upper.
    rank = (len(ordered) - 1) * pct

    # Vị trí dưới.
    lower = int(rank)

    # Vị trí trên.
    # min(...) để tránh vượt quá index cuối danh sách.
    upper = min(lower + 1, len(ordered) - 1)

    # Phần thập phân dùng làm trọng số nội suy.
    #
    # Ví dụ rank = 1.7:
    #   lower = 1
    #   weight = 0.7
    #
    # Kết quả sẽ gần ordered[upper] hơn ordered[lower].
    weight = rank - lower

    # Nội suy tuyến tính:
    #
    # Nếu weight = 0:
    #   lấy hoàn toàn ordered[lower].
    #
    # Nếu weight = 1:
    #   lấy hoàn toàn ordered[upper].
    #
    # Nếu weight = 0.5:
    #   lấy trung bình của hai giá trị.
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def load_raw_results(raw_dir: str | Path) -> list[dict]:
    """
    Đọc toàn bộ kết quả benchmark thô từ thư mục raw_dir.

    Hàm này tìm các file JSON có format tên:

        rto_interval_*min_run_*.json

    Ví dụ:
        rto_interval_1min_run_1.json
        rto_interval_1min_run_2.json
        rto_interval_10min_run_1.json

    Mỗi file JSON đại diện cho kết quả của một lần chạy benchmark.
    """

    # Danh sách chứa các kết quả đọc được từ file JSON.
    results = []

    # Duyệt qua tất cả file JSON benchmark theo thứ tự tên file.
    #
    # Path(raw_dir).glob(...):
    #   tìm các file khớp pattern.
    #
    # sorted(...):
    #   giúp thứ tự đọc file ổn định, dễ debug hơn.
    for path in sorted(Path(raw_dir).glob("rto_interval_*min_run_*.json")):

        # Mở file JSON với encoding utf-8.
        with path.open("r", encoding="utf-8") as fh:

            # Parse nội dung JSON thành dict rồi thêm vào results.
            results.append(json.load(fh))

    # Trả về danh sách kết quả raw.
    return results


def summarize_results(
    raw_results: Iterable[dict],
    *,
    txn_rate: float = 10.0,
) -> list[dict[str, float]]:
    """
    Tổng hợp kết quả benchmark thô thành các dòng summary.

    Input:
        raw_results:
            Danh sách kết quả benchmark đọc từ các file JSON.

        txn_rate:
            Transaction rate giả định, tính bằng transaction/giây.
            Giá trị này dùng cho mô hình estimate_recovery_cost().

    Output:
        Danh sách các dòng summary.
        Mỗi dòng tương ứng với một checkpoint interval.

    Ví dụ:
        interval 1 phút:
            run 1 -> rto_seconds = 0.12
            run 2 -> rto_seconds = 0.10
            run 3 -> rto_seconds = 0.14

        Sau khi summarize:
            mean_s
            median_s
            p99_s
            std_s
            io_cost
            cpu_cost
            comm_cost
            theory_rto_s
    """

    # Gom nhóm kết quả theo checkpoint interval.
    #
    # grouped có dạng:
    #
    # {
    #     1:  [result_run_1, result_run_2, ...],
    #     10: [result_run_1, result_run_2, ...],
    # }
    grouped: dict[int, list[dict]] = {}

    for result in raw_results:
        # Lấy interval_min từ kết quả raw.
        # Ép về int để dùng làm key.
        interval = int(result["interval_min"])

        # Nếu interval chưa có trong grouped thì tạo list mới.
        # Sau đó thêm result hiện tại vào nhóm tương ứng.
        grouped.setdefault(interval, []).append(result)

    # Danh sách các dòng summary cuối cùng.
    rows = []

    # Duyệt từng checkpoint interval theo thứ tự tăng dần.
    for interval in sorted(grouped):

        # Lấy danh sách các lần chạy benchmark của interval này.
        interval_results = grouped[interval]

        # Lấy danh sách RTO thực tế từ các lần chạy.
        #
        # rto_seconds là thời gian recovery đo được trong benchmark.
        rtos = [float(item["rto_seconds"]) for item in interval_results]

        # Tính số transaction in-doubt trung bình trong nhóm này.
        #
        # item.get("in_doubt_txns", 0):
        #   Nếu file raw không có field in_doubt_txns thì mặc định là 0.
        #
        # in_doubt_txns ảnh hưởng tới communication cost,
        # vì transaction in-doubt cần hỏi coordinator trong recovery.
        in_doubt_avg = statistics.mean(
            float(item.get("in_doubt_txns", 0))
            for item in interval_results
        )

        # Tính chi phí lý thuyết cho checkpoint interval hiện tại.
        #
        # estimate_recovery_cost() không đo thời gian thật.
        # Nó ước lượng chi phí dựa trên:
        # - checkpoint interval
        # - transaction rate
        # - số transaction in-doubt
        cost = estimate_recovery_cost(
            interval,
            txn_rate,
            in_doubt_txns=int(round(in_doubt_avg)),
        )

        # Tạo một dòng summary cho interval hiện tại.
        rows.append(
            {
                # Checkpoint interval tính theo phút.
                "interval_min": float(interval),

                # RTO trung bình qua nhiều lần chạy.
                "mean_s": statistics.mean(rtos),

                # Trung vị RTO.
                # Median ít bị ảnh hưởng bởi outlier hơn mean.
                "median_s": statistics.median(rtos),

                # P99 RTO.
                # Dùng để biểu diễn gần worst-case recovery time.
                "p99_s": percentile(rtos, 0.99),

                # Độ lệch chuẩn RTO.
                #
                # Nếu chỉ có một lần chạy thì không tính được stdev,
                # nên đặt là 0.0.
                "std_s": statistics.stdev(rtos) if len(rtos) > 1 else 0.0,

                # Chi phí I/O lý thuyết.
                "io_cost": cost["io"],

                # Chi phí CPU lý thuyết.
                "cpu_cost": cost["cpu"],

                # Chi phí communication lý thuyết.
                "comm_cost": cost["comm"],

                # RTO lý thuyết tính từ số I/O ước lượng.
                "theory_rto_s": cost["theory_rto_s"],
            }
        )

    # Trả về danh sách summary rows.
    return rows


def write_summary_csv(
    rows: Iterable[dict[str, float]],
    output_path: str | Path,
) -> None:
    """
    Ghi kết quả summary ra file CSV.

    File CSV này có thể dùng để:
    - vẽ biểu đồ Recovery Time vs Checkpoint Interval
    - đưa vào báo cáo
    - import vào Excel/Google Sheets
    - làm dữ liệu cho frontend chart
    """

    # Chuẩn hóa output_path về Path.
    path = Path(output_path)

    # Tạo thư mục cha nếu chưa tồn tại.
    #
    # Ví dụ output_path = "results/summary.csv"
    # thì dòng này tạo thư mục "results".
    path.parent.mkdir(parents=True, exist_ok=True)

    # Mở file CSV ở chế độ write.
    #
    # newline="":
    #   tránh lỗi dòng trống dư thừa trên Windows.
    #
    # encoding="utf-8":
    #   đảm bảo ghi được text ổn định.
    with path.open("w", newline="", encoding="utf-8") as fh:

        # Tạo DictWriter để ghi dict thành từng dòng CSV.
        #
        # fieldnames=SUMMARY_FIELDS:
        #   quy định thứ tự cột trong file CSV.
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)

        # Ghi dòng header.
        writer.writeheader()

        # Ghi từng dòng dữ liệu.
        for row in rows:

            # Chỉ ghi các field nằm trong SUMMARY_FIELDS.
            #
            # Cách này giúp CSV luôn có format cố định,
            # kể cả row có thêm field phụ khác.
            writer.writerow({field: row[field] for field in SUMMARY_FIELDS})


def analyze_raw_dir(
    raw_dir: str | Path,
    output_path: str | Path,
    *,
    txn_rate: float = 10.0,
) -> list[dict[str, float]]:
    """
    Hàm tổng hợp hoàn chỉnh cho bước phân tích benchmark.

    Hàm này làm 3 việc:

    1. Đọc toàn bộ file raw benchmark JSON trong raw_dir.
    2. Tổng hợp kết quả theo checkpoint interval.
    3. Ghi bảng summary ra file CSV.

    Sau đó trả về rows để code khác có thể tiếp tục dùng,
    ví dụ API trả về frontend hoặc vẽ chart.
    """

    # Đọc dữ liệu raw từ thư mục.
    raw_results = load_raw_results(raw_dir)

    # Tính các thống kê:
    # - mean
    # - median
    # - p99
    # - std
    # - cost model
    rows = summarize_results(raw_results, txn_rate=txn_rate)

    # Ghi kết quả tổng hợp ra CSV.
    write_summary_csv(rows, output_path)

    # Trả về kết quả để caller dùng tiếp nếu cần.
    return rows