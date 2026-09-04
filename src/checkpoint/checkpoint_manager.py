from __future__ import annotations

"""Ghi checkpoint marker vào WAL.

BEGIN_CHECKPOINT và END_CHECKPOINT giúp recovery không cần scan toàn bộ log.
Trong simulator, END_CHECKPOINT chỉ lưu redo_lsn để giữ metadata nhỏ gọn.
"""

from dataclasses import dataclass

from src.log.log_record import RecordType, WalWriter


@dataclass
class CheckpointManager:
    """Quản lý việc ghi cặp checkpoint marker vào WAL.

    fail_after_begin dùng cho scenario checkpoint failure: có BEGIN nhưng thiếu
    END, từ đó recovery phải bỏ qua checkpoint chưa hoàn chỉnh.
    """

    writer: WalWriter

    def write_checkpoint(self, *, fail_after_begin: bool = False) -> tuple[int, int | None]:
        # BEGIN đánh dấu checkpoint đang bắt đầu, nhưng chưa đủ để recovery tin cậy.
        begin = self.writer.append(RecordType.BEGIN_CHECKPOINT)
        if fail_after_begin:
            return begin.lsn, None
        # END xác nhận checkpoint hoàn tất; redo_lsn cho biết recovery scan từ đâu.
        end = self.writer.append(RecordType.END_CHECKPOINT, redo_lsn=begin.lsn)
        return begin.lsn, end.lsn
