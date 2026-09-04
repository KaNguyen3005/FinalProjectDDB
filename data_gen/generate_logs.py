from __future__ import annotations

"""Sinh WAL/snapshot cho custom config và benchmark.

Generator này tạo checkpoint định kỳ theo checkpoint_every, sau đó ghi nhiều
transaction có START/UPDATE và kết thúc bằng COMMIT, ABORT hoặc PREPARE/READY.
Một phần update được flush vào snapshot để recovery có tình huống cần REDO/UNDO.
"""

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.checkpoint.checkpoint_manager import CheckpointManager
from src.log.log_record import RecordType, WalWriter
from src.storage import create_snapshot, page_count, read_page, write_page


def generate_logs(
    log_path: str | Path,
    snapshot_path: str | Path,
    *,
    transactions: int,
    checkpoint_every: int,
    seed: int = 42,
    pages: int = 1_000,
) -> None:
    """
    Sinh dữ liệu giả lập cho WAL recovery.

    Hàm này tạo:
    - Một file snapshot: mô phỏng dữ liệu hiện tại của database trên disk.
    - Một file WAL log: ghi lại các thao tác START, UPDATE, COMMIT, ABORT, PREPARE, READY.
    
    Mục đích:
    - Tạo nhiều transaction giả lập.
    - Một số transaction commit.
    - Một số transaction abort.
    - Một số transaction rơi vào trạng thái 2PC PREPARE/READY.
    - Một số thay đổi được ghi vào snapshot, một số chỉ nằm trong WAL.
    
    Điều này giúp test thuật toán recovery:
    - Transaction đã COMMIT thì cần REDO nếu thiếu.
    - Transaction đã ABORT thì cần UNDO nếu đã ghi xuống snapshot.
    - Transaction PREPARE/READY thì cần hỏi coordinator để quyết định.
    """

    # Tạo bộ sinh số ngẫu nhiên riêng.
    # Dùng seed để mỗi lần chạy cùng seed thì kết quả random giống nhau.
    # Điều này rất hữu ích khi debug hoặc test.
    rng = random.Random(seed)

    # Chuyển đường dẫn log_path sang Path để dễ thao tác file/thư mục.
    log_file = Path(log_path)

    # Chuyển đường dẫn snapshot_path sang Path.
    snapshot_file = Path(snapshot_path)

    # Tạo thư mục chứa file log nếu thư mục đó chưa tồn tại.
    # Ví dụ log_path = "data/wal/log.bin"
    # thì dòng này sẽ tạo thư mục "data/wal".
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Xóa file WAL log cũ nếu nó đã tồn tại.
    # missing_ok=True nghĩa là nếu file chưa tồn tại thì không báo lỗi.
    log_file.unlink(missing_ok=True)

    # Tạo snapshot mới từ đầu.
    # Snapshot ở đây mô phỏng trạng thái dữ liệu ban đầu của database trên disk.
    #
    # Trong database thật:
    # - page có thể là block 4KB, 8KB, 16KB...
    #
    # Trong demo này:
    # - mỗi page được đơn giản hóa thành 1 giá trị số.
    create_snapshot(snapshot_file, pages, seed=seed)

    # Đếm số page hiện có trong snapshot.
    # pages_available cho biết có bao nhiêu page có thể được update.
    pages_available = page_count(snapshot_file)

    # Tạo WalWriter để ghi các record vào file WAL log.
    # Ví dụ ghi START, UPDATE, COMMIT, ABORT...
    writer = WalWriter(log_file)

    # Tạo CheckpointManager để ghi checkpoint vào WAL.
    # Checkpoint giúp recovery không cần scan log từ đầu.
    checkpointer = CheckpointManager(writer)

    # Ghi checkpoint đầu tiên.
    # Mục đích: recovery luôn có một điểm bắt đầu hợp lệ.
    checkpointer.write_checkpoint()

    # Sinh lần lượt các transaction.
    # txn_id chạy từ 1 đến transactions.
    for txn_id in range(1, transactions + 1):

        # Mỗi transaction bắt đầu bằng record START.
        # Record này cho biết transaction đã bắt đầu chạy.
        writer.append(RecordType.START, txn_id=txn_id)

        # Mỗi transaction sẽ có ngẫu nhiên từ 1 đến 3 UPDATE.
        # Ví dụ:
        #   START T1
        #   UPDATE T1 page 10
        #   UPDATE T1 page 20
        #   COMMIT T1
        updates = rng.randint(1, 3)

        # Sinh các update cho transaction hiện tại.
        for _ in range(updates):

            # Chọn ngẫu nhiên một page trong snapshot.
            # page_id là chỉ số page cần sửa.
            page_id = rng.randrange(pages_available)

            # Đọc giá trị hiện tại của page.
            # Đây là before_image, tức giá trị trước khi update.
            before = read_page(snapshot_file, page_id)

            # Tạo giá trị mới cho page.
            # Trong demo này, page chỉ là một số nên ta cộng thêm 1 đến 100.
            # Đây là after_image, tức giá trị sau khi update.
            after = before + rng.randint(1, 100)

            # Ghi UPDATE record vào WAL.
            #
            # WAL sẽ lưu:
            # - transaction nào sửa
            # - sửa page nào
            # - giá trị trước khi sửa là gì
            # - giá trị sau khi sửa là gì
            #
            # before_image dùng để UNDO nếu transaction abort.
            # after_image dùng để REDO nếu transaction commit.
            writer.append(
                RecordType.UPDATE,
                txn_id=txn_id,
                page_id=page_id,
                before_image=before,
                after_image=after,
            )

            # Có 80% khả năng update được ghi luôn vào snapshot.
            #
            # Điều này mô phỏng tình huống thực tế:
            # - Có update đã được flush xuống disk.
            # - Có update vẫn chỉ nằm trong WAL.
            #
            # Vì vậy khi recovery, hệ thống phải kiểm tra:
            # - Transaction commit chưa?
            # - Nếu commit thì redo.
            # - Nếu abort thì undo.
            if rng.random() < 0.8:
                write_page(snapshot_file, page_id, after)

        # Sau khi ghi các UPDATE, ta quyết định kết quả cuối của transaction.
        # Transaction có thể:
        # - COMMIT: thành công.
        # - ABORT: bị hủy.
        # - PREPARE/READY: trạng thái two-phase commit, đang chờ coordinator.
        decision = rng.random()

        # Khoảng 72% transaction sẽ COMMIT.
        if decision < 0.72:
            writer.append(RecordType.COMMIT, txn_id=txn_id)

        # Từ 72% đến dưới 90%, tức khoảng 18% transaction sẽ ABORT.
        elif decision < 0.9:
            writer.append(RecordType.ABORT, txn_id=txn_id)

        # Còn lại khoảng 10% transaction sẽ ở trạng thái 2PC.
        # PREPARE/READY nghĩa là transaction đã sẵn sàng commit,
        # nhưng vẫn cần coordinator đưa ra quyết định cuối cùng.
        else:
            writer.append(RecordType.PREPARE, txn_id=txn_id)
            writer.append(RecordType.READY, txn_id=txn_id)

        # Ghi checkpoint định kỳ.
        #
        # checkpoint_every > 0:
        #   Có bật checkpoint.
        #
        # txn_id % checkpoint_every == 0:
        #   Cứ sau mỗi checkpoint_every transaction thì ghi checkpoint.
        #
        # txn_id != transactions:
        #   Không ghi checkpoint ở transaction cuối trong đoạn này.
        #   Có thể vì sau cùng chương trình sẽ có xử lý riêng hoặc không cần checkpoint nữa.
        if checkpoint_every > 0 and txn_id % checkpoint_every == 0 and txn_id != transactions:
            checkpointer.write_checkpoint()

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a binary WAL file.")
    parser.add_argument("--transactions", type=int, default=10_000)
    parser.add_argument("--checkpoint-every", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pages", type=int, default=10_000)
    parser.add_argument("--output", type=Path, default=Path("data/transaction_log.bin"))
    parser.add_argument("--snapshot", type=Path, default=Path("data/db_snapshot.bin"))
    args = parser.parse_args()

    generate_logs(
        args.output,
        args.snapshot,
        transactions=args.transactions,
        checkpoint_every=args.checkpoint_every,
        seed=args.seed,
        pages=args.pages,
    )
    print(f"generated WAL: {args.output} ({args.transactions} transactions)")


if __name__ == "__main__":
    main()
