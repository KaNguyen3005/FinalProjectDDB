from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_gen.generate_logs import generate_logs
from src.crash.recovery_timer import RecoveryTimer
from src.integrity.integrity_checker import sha256_file
from src.recovery.recovery_manager import RecoveryManager


def crash_and_recover(
    *,
    interval: int,
    transactions: int,
    pages: int,
    seed: int,
    data_dir: Path,
    verbose_events: bool,
) -> None:
    """CLI smoke path: generate data, run recovery, and print RTO metrics."""
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "transaction_log.bin"
    snapshot_path = data_dir / "db_snapshot.bin"

    checkpoint_every = max(1, interval * 10)
    generate_logs(
        log_path,
        snapshot_path,
        transactions=transactions,
        checkpoint_every=checkpoint_every,
        seed=seed,
        pages=pages,
    )

    before_hash = sha256_file(snapshot_path)
    timer = RecoveryTimer()
    timer.start()

    def emit(event: dict) -> None:
        """Optional event sink for debugging recovery pass output."""
        if verbose_events:
            print(event)

    result = RecoveryManager().recover(log_path, snapshot_path, event_cb=emit)
    timer.stop()
    after_hash = sha256_file(snapshot_path)

    print(f"RTO seconds: {result.rto_seconds:.6f}")
    print(f"Checkpoint interval: {interval} min")
    print(f"Redo LSN: {result.redo_lsn}")
    print(f"Records scanned: {result.records_scanned}")
    print(f"Records redone: {result.records_redone}")
    print(f"Records undone: {result.records_undone}")
    print(f"In-doubt txns: {len(result.in_doubt)}")
    print(f"Snapshot SHA-256 before recovery: {before_hash}")
    print(f"Snapshot SHA-256 after recovery:  {after_hash}")


def main() -> None:
    """Parse CLI options for the core simulator."""
    parser = argparse.ArgumentParser(description="RTO disaster recovery simulator.")
    parser.add_argument("--crash-and-recover", action="store_true")
    parser.add_argument("--interval", type=int, default=5, help="Checkpoint interval in benchmark minutes.")
    parser.add_argument("--transactions", type=int, default=200)
    parser.add_argument("--pages", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--verbose-events", action="store_true")
    args = parser.parse_args()

    if args.crash_and_recover:
        crash_and_recover(
            interval=args.interval,
            transactions=args.transactions,
            pages=args.pages,
            seed=args.seed,
            data_dir=args.data_dir,
            verbose_events=args.verbose_events,
        )
        return

    parser.print_help()


if __name__ == "__main__":
    main()
