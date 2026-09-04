from __future__ import annotations

"""Process node giả lập ghi WAL liên tục cho các thử nghiệm crash."""

import random
import time
from multiprocessing import Event, Process
from pathlib import Path

from src.log.log_record import RecordType, WalWriter


class SimulatedNode(Process):
    """Một process nhỏ sinh transaction commit đều đặn vào WAL."""

    def __init__(self, node_id: str, log_path: str | Path, stop_event: Event, seed: int = 42) -> None:
        super().__init__()
        self.node_id = node_id
        self.log_path = Path(log_path)
        self.stop_event = stop_event
        self.seed = seed

    def run(self) -> None:
        # Mỗi vòng tạo một transaction START -> UPDATE -> COMMIT để WAL tăng dần.
        rng = random.Random(self.seed)
        writer = WalWriter(self.log_path, node_id=self.node_id)
        txn_id = 1
        while not self.stop_event.is_set():
            writer.append(RecordType.START, txn_id=txn_id)
            page_id = rng.randrange(100)
            before = rng.randint(0, 1_000)
            writer.append(
                RecordType.UPDATE,
                txn_id=txn_id,
                page_id=page_id,
                before_image=before,
                after_image=before + 1,
            )
            writer.append(RecordType.COMMIT, txn_id=txn_id)
            txn_id += 1
            time.sleep(0.05)
