from __future__ import annotations

"""Mô hình chi phí lý thuyết để so sánh xu hướng RTO theo checkpoint interval."""


def estimate_recovery_cost(
    interval_min: int,
    txn_rate: float,
    *,
    C_io: float = 1.0,
    C_cpu: float = 0.01,
    C_msg: float = 5.0,
    C_tr: float = 0.0001,
    avg_record_bytes: int = 200,
    page_size: int = 4096,
    in_doubt_txns: int = 0,
    io_latency_s: float = 0.010,
    cpu_unit_s: float = 0.00001,
    message_latency_s: float = 0.002,
    network_byte_s: float = 0.00000001,
) -> dict[str, float]:
    """
    Ước lượng chi phí recovery dựa trên mô hình chi phí phân tán.

    Công thức tổng quát:

        Cost = C_io * #IO
             + C_cpu * #CPU
             + C_msg * #MSG
             + C_tr * #BYTES

    Trong đó:
    - #IO: số lần đọc/ghi I/O ước lượng khi scan WAL.
    - #CPU: lượng xử lý CPU ước lượng khi phân tích log.
    - #MSG: số message trao đổi trong hệ phân tán.
    - #BYTES: số byte truyền qua mạng.
    - C_io, C_cpu, C_msg, C_tr: hệ số trọng số cho từng loại chi phí.

    Hàm này không đo recovery time thật.
    Nó chỉ tạo ra một giá trị lý thuyết để so sánh:
    - checkpoint interval ngắn, ví dụ 1 phút
    - checkpoint interval dài, ví dụ 10 phút

    Ý tưởng:
    Checkpoint interval càng dài thì WAL tail sau checkpoint càng lớn,
    recovery phải scan nhiều log hơn, do đó chi phí recovery tăng.
    """

    # Ước lượng số byte log cần scan sau checkpoint gần nhất.
    #
    # interval_min:
    #   Khoảng checkpoint theo phút.
    #
    # interval_min * 60:
    #   Đổi phút sang giây.
    #
    # txn_rate:
    #   Số transaction mỗi giây.
    #
    # avg_record_bytes:
    #   Kích thước trung bình của một log record.
    #
    # Ví dụ:
    #   interval_min = 10
    #   txn_rate = 100 transaction/giây
    #   avg_record_bytes = 200 bytes
    #
    #   log_bytes = 10 * 60 * 100 * 200
    #
    # Nghĩa là trong 10 phút, hệ thống sinh ra khoảng đó byte log.
    log_bytes = max(0.0, interval_min * 60 * txn_rate * avg_record_bytes)

    # Ước lượng số lần I/O cần để đọc lượng log này.
    #
    # page_size mặc định là 4096 bytes, tương đương 4KB.
    #
    # Nếu log_bytes = 40960 bytes,
    # page_size = 4096 bytes,
    # thì num_io = 10 page I/O.
    num_io = log_bytes / page_size

    # Ước lượng lượng CPU cần xử lý log.
    #
    # Ở đây giả định cứ mỗi 50 bytes log tương ứng với 1 đơn vị CPU work.
    # Đây là hệ số mô phỏng, không phải đơn vị CPU thật.
    #
    # Nếu muốn mô hình sát hơn, có thể thay 50 bằng benchmark thực tế.
    num_cpu = log_bytes / 50

    # Ước lượng số message mạng trong recovery phân tán.
    #
    # 4:
    #   Số message cơ bản của recovery/coordinator protocol.
    #
    # in_doubt_txns * 2:
    #   Mỗi transaction in-doubt cần thêm message để hỏi coordinator
    #   và nhận quyết định commit/abort.
    #
    # max(0, in_doubt_txns):
    #   Đảm bảo số lượng transaction in-doubt không bị âm.
    num_msg = 4 + max(0, in_doubt_txns) * 2

    # Ước lượng số byte truyền qua mạng.
    #
    # 1024:
    #   Lượng dữ liệu mạng cơ bản.
    #
    # in_doubt_txns * 512:
    #   Mỗi transaction in-doubt phát sinh thêm khoảng 512 bytes.
    #
    # Đây là con số mô phỏng để thể hiện:
    # càng nhiều transaction in-doubt thì chi phí communication càng cao.
    num_bytes = 1024 + max(0, in_doubt_txns) * 512

    # Chi phí I/O.
    #
    # C_io là trọng số chi phí cho mỗi đơn vị I/O.
    io_cost = C_io * num_io

    # Chi phí CPU.
    #
    # C_cpu là trọng số chi phí cho mỗi đơn vị CPU work.
    cpu_cost = C_cpu * num_cpu

    # Chi phí truyền thông trong hệ phân tán.
    #
    # Gồm:
    # - chi phí theo số message
    # - chi phí theo số byte truyền qua mạng
    comm_cost = C_msg * num_msg + C_tr * num_bytes

    # Tổng chi phí recovery lý thuyết.
    total = io_cost + cpu_cost + comm_cost

    # Quy đổi workload ước lượng sang thời gian lý thuyết.
    #
    # Các hệ số *_s khác với C_io/C_cpu/C_msg/C_tr:
    # - C_* dùng để tạo cost unit cho biểu đồ breakdown.
    # - *_s dùng để ước lượng số giây cho theory_rto_s.
    #
    # Nhờ vậy theory_rto_s phản ánh đủ 3 nguồn trễ:
    # I/O scan WAL, CPU phân tích log, và communication khi hỏi coordinator.
    io_time_s = num_io * io_latency_s
    cpu_time_s = num_cpu * cpu_unit_s
    comm_time_s = num_msg * message_latency_s + num_bytes * network_byte_s
    theory_rto_s = io_time_s + cpu_time_s + comm_time_s

    # Trả về breakdown chi phí.
    #
    # io:
    #   Thành phần chi phí I/O.
    #
    # cpu:
    #   Thành phần chi phí CPU.
    #
    # comm:
    #   Thành phần chi phí communication.
    #
    # total:
    #   Tổng chi phí lý thuyết.
    #
    # theory_rto_s:
    #   RTO lý thuyết tính bằng giây từ I/O + CPU + communication time.
    #
    # io_time_s / cpu_time_s / comm_time_s:
    #   Breakdown thời gian lý thuyết, dùng để giải thích theory_rto_s.
    #
    # log_bytes:
    #   Số byte WAL ước lượng phải scan.
    #
    # messages:
    #   Số message mạng ước lượng.
    return {
        "io": io_cost,
        "cpu": cpu_cost,
        "comm": comm_cost,
        "total": total,
        "theory_rto_s": theory_rto_s,
        "io_time_s": io_time_s,
        "cpu_time_s": cpu_time_s,
        "comm_time_s": comm_time_s,
        "log_bytes": log_bytes,
        "messages": float(num_msg),
    }
