from __future__ import annotations

from dataclasses import dataclass

from src.log.log_record import RecordType, WalWriter


@dataclass
class CheckpointManager:
    writer: WalWriter

    def write_checkpoint(self, *, fail_after_begin: bool = False) -> tuple[int, int | None]:
        begin = self.writer.append(RecordType.BEGIN_CHECKPOINT)
        if fail_after_begin:
            return begin.lsn, None
        # In the simulator, dirty-page flushing is synchronous and abstracted.
        end = self.writer.append(RecordType.END_CHECKPOINT, redo_lsn=begin.lsn)
        return begin.lsn, end.lsn
