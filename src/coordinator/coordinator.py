from __future__ import annotations

"""Coordinator giả lập cho recovery của transaction 2PC."""

from dataclasses import dataclass, field
from typing import Literal


CoordinatorDecision = Literal["COMMIT", "ABORT"]


@dataclass
class CoordinatorSimulator:
    """
    Bộ mô phỏng coordinator 2PC dùng trong demo recovery.

    Khi participant recovery gặp PREPARE/READY chưa có quyết định cuối, nó hỏi
    coordinator này để biết transaction toàn cục COMMIT hay ABORT.
    """

    decisions: dict[int, CoordinatorDecision] = field(default_factory=dict)

    def resolve(self, txn_id: int) -> CoordinatorDecision | None:
        """Trả về quyết định cuối nếu coordinator có log của transaction đó."""
        return self.decisions.get(txn_id)
