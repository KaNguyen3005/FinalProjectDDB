from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


CoordinatorDecision = Literal["COMMIT", "ABORT"]


@dataclass
class CoordinatorSimulator:
    """
    Small 2PC coordinator simulator for demo recovery.

    It represents the surviving coordinator log. When a recovering participant
    finds an in-doubt PREPARE/READY transaction, it asks this simulator for the
    final global decision.
    """

    decisions: dict[int, CoordinatorDecision] = field(default_factory=dict)

    def resolve(self, txn_id: int) -> CoordinatorDecision | None:
        return self.decisions.get(txn_id)
