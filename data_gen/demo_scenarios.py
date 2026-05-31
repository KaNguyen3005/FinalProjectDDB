from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from src.checkpoint.checkpoint_manager import CheckpointManager
from src.log.log_record import RecordType, WalWriter
from src.storage import create_snapshot, read_page, write_page


# Các trạng thái cuối cùng mà một transaction trong demo có thể nhận.
#
# COMMIT:
#   Transaction hoàn tất thành công.
#
# ABORT:
#   Transaction bị hủy có chủ đích.
#
# IN_DOUBT:
#   Transaction đã PREPARE/READY trong cơ chế 2PC nhưng chưa có quyết định cuối cùng.
#   Khi recovery, hệ thống cần hỏi coordinator transaction này commit hay abort.
#
# LOSER:
#   Transaction đã START/UPDATE nhưng chưa COMMIT/ABORT.
#   Đây là transaction đang dở dang tại thời điểm crash.
#   Khi recovery, nó cần bị UNDO.
Decision = Literal["COMMIT", "ABORT", "IN_DOUBT", "LOSER"]


@dataclass(frozen=True)
class DemoScenario:
    # Mã định danh scenario, dùng để chọn demo cần chạy.
    id: str

    # Tên ngắn gọn của scenario để hiển thị trên UI hoặc báo cáo.
    title: str

    # Mô tả scenario: nó đang kiểm thử tình huống recovery nào.
    description: str

    # Khoảng checkpoint theo phút, dùng cho mục đích mô tả/benchmark.
    #
    # Lưu ý quan trọng:
    # Trong file demo này, checkpoint không được tạo dựa trên đồng hồ thật.
    # Các scenario được viết thủ công để mô phỏng checkpoint ngắn/dài.
    #
    # Ví dụ:
    #   checkpoint_interval_min = 1
    #   nghĩa là scenario đại diện cho checkpoint ngắn.
    #
    #   checkpoint_interval_min = 10
    #   nghĩa là scenario đại diện cho checkpoint dài.
    #
    # Nhưng bản thân code không đợi 1 phút hay 10 phút thật.
    checkpoint_interval_min: int

    # Số transaction trong scenario.
    transactions: int

    # Số page trong snapshot.
    #
    # Trong database thật, page thường là block dữ liệu như 4KB, 8KB, 16KB.
    # Trong demo này, mỗi page được đơn giản hóa thành một giá trị số.
    pages: int

    # Kết quả recovery kỳ vọng của scenario.
    expected: str

    # Quyết định từ coordinator cho các transaction IN_DOUBT.
    #
    # Ví dụ:
    #   {6: "COMMIT", 8: "ABORT"}
    #
    # Nghĩa là khi recovery gặp transaction 6 đang in-doubt,
    # coordinator nói transaction 6 commit.
    #
    # Khi gặp transaction 8 đang in-doubt,
    # coordinator nói transaction 8 abort.
    coordinator_decisions: dict[int, str] = None

    # Dùng để mô phỏng checkpoint bị lỗi.
    #
    # Nếu True:
    #   hệ thống ghi BEGIN_CHECKPOINT
    #   nhưng crash trước khi ghi END_CHECKPOINT.
    #
    # Recovery phải bỏ qua checkpoint chưa hoàn chỉnh này.
    checkpoint_failure: bool = False

    def to_dict(self) -> dict:
        # Chuyển dataclass thành dict để dễ trả về API/UI.
        data = asdict(self)

        # Nếu coordinator_decisions là None thì đổi thành dict rỗng.
        # Làm vậy giúp phía frontend/API không phải xử lý giá trị None.
        data["coordinator_decisions"] = self.coordinator_decisions or {}
        return data

# Danh sách các kịch bản demo recovery.
#
# Mỗi scenario mô phỏng một tình huống crash/recovery khác nhau:
#
# 1. fast_checkpoint_clean:
#    Checkpoint gần thời điểm crash.
#    WAL tail ngắn.
#    Recovery nhanh.
#
# 2. long_checkpoint_heavy_redo:
#    Checkpoint xa thời điểm crash.
#    WAL tail dài.
#    Recovery phải scan nhiều record hơn và redo nhiều hơn.
#
# 3. global_undo_loser:
#    Có transaction abort hoặc transaction chưa kết thúc.
#    Recovery phải Global Undo.
#
# 4. in_doubt_2pc:
#    Có transaction PREPARE/READY nhưng chưa COMMIT/ABORT.
#    Recovery phải hỏi coordinator.
#
# 5. checkpoint_failure:
#    Có BEGIN_CHECKPOINT nhưng không có END_CHECKPOINT.
#    Recovery phải bỏ qua checkpoint chưa hoàn chỉnh.
SCENARIOS: dict[str, DemoScenario] = {
    "fast_checkpoint_clean": DemoScenario(
        id="fast_checkpoint_clean",
        title="Fast checkpoint: clean recovery",
        description="Short log tail with committed transactions only; shows fast Analysis and Partial Redo.",
        checkpoint_interval_min=1,
        transactions=8,
        pages=24,
        expected="Low RTO, no Global Undo, no in-doubt transactions.",
        coordinator_decisions={},
    ),

    "long_checkpoint_heavy_redo": DemoScenario(
        id="long_checkpoint_heavy_redo",
        title="Long checkpoint: heavy redo",
        description="Longer tail after the last checkpoint; committed updates dominate recovery work.",
        checkpoint_interval_min=10,
        transactions=28,
        pages=48,
        expected="More records scanned and more Partial Redo records.",
        coordinator_decisions={},
    ),

    "global_undo_loser": DemoScenario(
        id="global_undo_loser",
        title="Loser transactions: Global Undo",
        description="Includes aborted and incomplete transactions after checkpoint.",
        checkpoint_interval_min=5,
        transactions=14,
        pages=32,
        expected="Global Undo restores before images for loser and aborted transactions.",
        coordinator_decisions={},
    ),

    "in_doubt_2pc": DemoScenario(
        id="in_doubt_2pc",
        title="2PC in-doubt transaction",
        description="Includes PREPARE and READY without a final COMMIT or ABORT.",
        checkpoint_interval_min=5,
        transactions=12,
        pages=32,
        expected="Recovery asks the coordinator: TXN#6 commits globally, TXN#8 aborts globally.",
        coordinator_decisions={6: "COMMIT", 8: "ABORT"},
    ),

    "checkpoint_failure": DemoScenario(
        id="checkpoint_failure",
        title="Checkpoint failure: BEGIN without END",
        description="Writes BEGIN_CHECKPOINT and crashes before END_CHECKPOINT is logged.",
        checkpoint_interval_min=10,
        transactions=10,
        pages=24,
        expected="Recovery ignores the incomplete checkpoint and falls back to the prior valid END_CHECKPOINT.",
        coordinator_decisions={},
        checkpoint_failure=True,
    ),
}


def list_scenarios() -> list[dict]:
    return [scenario.to_dict() for scenario in SCENARIOS.values()]


def get_scenario(scenario_id: str) -> DemoScenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise ValueError(f"unknown demo scenario: {scenario_id}") from exc


def generate_demo_scenario(
    scenario_id: str,
    log_path: str | Path,
    snapshot_path: str | Path,
    *,
    seed: int = 42,
) -> DemoScenario:
    # Lấy thông tin scenario theo scenario_id.
    # Nếu scenario_id không tồn tại, get_scenario sẽ raise ValueError.
    scenario = get_scenario(scenario_id)

    # Chuẩn hóa đường dẫn WAL log và snapshot về kiểu Path.
    log_file = Path(log_path)
    snapshot_file = Path(snapshot_path)

    # Tạo thư mục chứa WAL log nếu chưa tồn tại.
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Xóa WAL log cũ để mỗi lần chạy scenario đều bắt đầu sạch.
    log_file.unlink(missing_ok=True)

    # Tạo snapshot mới.
    #
    # Snapshot mô phỏng dữ liệu hiện tại của database trên disk.
    # Trong demo này, mỗi page trong snapshot là một giá trị số đơn giản.
    #
    # seed giúp dữ liệu snapshot có thể tái lập:
    # cùng seed -> cùng dữ liệu ban đầu.
    create_snapshot(snapshot_file, scenario.pages, seed=seed)

    # Tạo writer để ghi các record vào WAL log.
    writer = WalWriter(log_file)

    # Tạo checkpoint manager.
    # Object này chịu trách nhiệm ghi BEGIN_CHECKPOINT / END_CHECKPOINT.
    checkpoint = CheckpointManager(writer)

    # Ghi checkpoint đầu tiên.
    #
    # Ý nghĩa:
    # Recovery luôn có một checkpoint hợp lệ ban đầu để bám vào.
    #
    # Lưu ý:
    # Nếu write_checkpoint hiện tại chỉ ghi BEGIN_CHECKPOINT rồi END_CHECKPOINT,
    # thì nó mới là checkpoint dạng marker.
    # Muốn sát lý thuyết Gray hơn, END_CHECKPOINT nên chứa thêm metadata,
    # ví dụ active transactions hoặc dirty page table.
    checkpoint.write_checkpoint()

    # Mỗi nhánh dưới đây tạo một câu chuyện recovery riêng.
    #
    # Các scenario này không sinh transaction random.
    # Chúng cố tình ghi WAL theo kế hoạch cố định để demo dễ hiểu và dễ tái lập.
    if scenario_id == "fast_checkpoint_clean":
        # Scenario checkpoint nhanh:
        #
        # 1. Ghi 4 transaction commit.
        # 2. Ghi checkpoint.
        # 3. Ghi thêm 4 transaction commit.
        #
        # Sau checkpoint cuối, WAL tail ngắn.
        # Recovery scan ít record nên recovery time thấp.
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(5, 9)])

    elif scenario_id == "long_checkpoint_heavy_redo":
        # Scenario checkpoint dài:
        #
        # 1. Ghi vài transaction commit ban đầu.
        # 2. Ghi checkpoint.
        # 3. Sau checkpoint, ghi rất nhiều transaction commit.
        #
        # Vì checkpoint nằm xa điểm crash,
        # recovery phải scan nhiều WAL record sau checkpoint hơn.
        # Đây là scenario dùng để minh họa checkpoint interval dài
        # làm tăng recovery time.
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 4)])
        checkpoint.write_checkpoint()
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 3) for txn in range(4, 29)])

    elif scenario_id == "global_undo_loser":
        # Scenario Global Undo:
        #
        # Sau checkpoint có nhiều loại transaction:
        # - COMMIT: cần REDO nếu cần.
        # - ABORT: cần đảm bảo thay đổi bị undo.
        # - LOSER: transaction chưa kết thúc tại thời điểm crash, cần UNDO.
        #
        # Scenario này kiểm thử khả năng phục hồi before_image.
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(
            writer,
            snapshot_file,
            [
                (5, "COMMIT", 2),
                (6, "ABORT", 2),
                (7, "LOSER", 2),
                (8, "COMMIT", 1),
                (9, "LOSER", 3),
                (10, "ABORT", 1),
                (11, "COMMIT", 2),
                (12, "LOSER", 1),
                (13, "COMMIT", 1),
                (14, "COMMIT", 1),
            ],
        )

    elif scenario_id == "in_doubt_2pc":
        # Scenario transaction phân tán 2PC:
        #
        # Một số transaction ghi PREPARE/READY nhưng không có COMMIT/ABORT.
        # Đây là trạng thái in-doubt.
        #
        # Khi recovery, hệ thống không được tự đoán.
        # Nó phải hỏi coordinator:
        # - TXN 6 commit hay abort?
        # - TXN 8 commit hay abort?
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(
            writer,
            snapshot_file,
            [
                (5, "COMMIT", 2),
                (6, "IN_DOUBT", 2),
                (7, "COMMIT", 1),
                (8, "IN_DOUBT", 1),
                (9, "ABORT", 1),
                (10, "COMMIT", 2),
                (11, "LOSER", 1),
                (12, "COMMIT", 1),
            ],
        )

    elif scenario_id == "checkpoint_failure":
        # Scenario checkpoint bị lỗi:
        #
        # 1. Có một checkpoint hợp lệ trước đó.
        # 2. Hệ thống bắt đầu ghi checkpoint mới.
        # 3. Nhưng crash xảy ra sau BEGIN_CHECKPOINT và trước END_CHECKPOINT.
        #
        # Theo lý thuyết checkpoint:
        # checkpoint chỉ hợp lệ khi có đủ BEGIN_CHECKPOINT và END_CHECKPOINT.
        #
        # Vì vậy recovery phải bỏ qua checkpoint chưa hoàn chỉnh
        # và quay về checkpoint hợp lệ trước đó.
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(1, 5)])
        checkpoint.write_checkpoint()
        _write_plan(writer, snapshot_file, [(txn, "COMMIT", 1) for txn in range(5, 8)])

        # Cố tình ghi checkpoint lỗi:
        # chỉ có BEGIN_CHECKPOINT, không có END_CHECKPOINT.
        checkpoint.write_checkpoint(fail_after_begin=True)

        # Sau checkpoint lỗi, ghi thêm các loser transaction.
        # Khi recovery, các transaction này phải bị UNDO.
        _write_plan(writer, snapshot_file, [(txn, "LOSER", 1) for txn in range(8, 11)])

    else:
        raise ValueError(f"unknown demo scenario: {scenario_id}")

    # Trả về thông tin scenario để UI/API có thể hiển thị expected result.
    return scenario


def _write_plan(
    writer: WalWriter,
    snapshot_path: Path,
    plan: list[tuple[int, Decision, int]],
) -> None:
    # Tính số page trong snapshot.
    #
    # Mỗi page trong demo đang được lưu bằng 8 bytes.
    # Vì vậy:
    #   số page = kích thước file snapshot / 8
    #
    # max(1, ...) đảm bảo luôn có ít nhất 1 page,
    # tránh lỗi chia/modulo với 0.
    page_count = max(1, snapshot_path.stat().st_size // 8)

    # plan là danh sách các transaction cần ghi vào WAL.
    #
    # Mỗi phần tử có dạng:
    #   (txn_id, decision, updates)
    #
    # Ví dụ:
    #   (5, "COMMIT", 2)
    #
    # Nghĩa là:
    #   transaction 5
    #   có 2 update
    #   kết thúc bằng COMMIT
    for txn_id, decision, updates in plan:

        # Ghi START record.
        # Mọi transaction trong WAL đều bắt đầu bằng START.
        writer.append(RecordType.START, txn_id=txn_id)

        # Ghi các UPDATE record cho transaction hiện tại.
        for index in range(updates):

            # Chọn page theo công thức deterministic.
            #
            # Không dùng random ở đây để scenario luôn tái lập được.
            # Cùng scenario sẽ luôn tạo ra cùng WAL.
            page_id = (txn_id * 7 + index * 5) % page_count

            # Đọc giá trị hiện tại của page.
            # Đây là before_image, dùng cho UNDO.
            before = read_page(snapshot_path, page_id)

            # Tạo giá trị mới.
            #
            # Công thức này giúp mỗi transaction tạo ra giá trị khác nhau,
            # dễ quan sát khi debug.
            after = before + txn_id * 100 + index + 1

            # Ghi UPDATE vào WAL.
            #
            # before_image:
            #   giá trị trước khi update, dùng để undo.
            #
            # after_image:
            #   giá trị sau khi update, dùng để redo.
            writer.append(
                RecordType.UPDATE,
                txn_id=txn_id,
                page_id=page_id,
                before_image=before,
                after_image=after,
            )

            # Ghi luôn after_image vào snapshot.
            #
            # Điều này mô phỏng tình huống update đã được flush xuống disk.
            # Nếu transaction sau đó ABORT hoặc LOSER,
            # recovery phải dùng before_image để UNDO.
            write_page(snapshot_path, page_id, after)

        # Nếu transaction commit:
        # recovery xem đây là winner transaction.
        # Các update của nó cần được giữ lại/redo nếu cần.
        if decision == "COMMIT":
            writer.append(RecordType.COMMIT, txn_id=txn_id)

        # Nếu transaction abort:
        # recovery phải đảm bảo các update của nó bị rollback.
        elif decision == "ABORT":
            writer.append(RecordType.ABORT, txn_id=txn_id)

        # Nếu transaction in-doubt:
        # ghi PREPARE và READY nhưng không ghi COMMIT/ABORT.
        #
        # Đây là tình huống 2PC:
        # participant đã sẵn sàng,
        # nhưng chưa biết quyết định cuối cùng từ coordinator.
        elif decision == "IN_DOUBT":
            writer.append(RecordType.PREPARE, txn_id=txn_id)
            writer.append(RecordType.READY, txn_id=txn_id)

        # Nếu transaction là loser:
        # không ghi COMMIT, ABORT, PREPARE hay READY.
        #
        # Nghĩa là crash xảy ra khi transaction còn đang chạy.
        # Khi recovery, transaction này phải bị UNDO.
        elif decision == "LOSER":
            continue

        # Bảo vệ nếu truyền decision không hợp lệ.
        else:
            raise ValueError(f"unsupported decision: {decision}")