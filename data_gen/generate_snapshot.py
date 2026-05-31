from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storage import create_snapshot


def main() -> None:
    """CLI helper for generating only the snapshot file."""
    parser = argparse.ArgumentParser(description="Generate a binary snapshot file.")
    parser.add_argument("--pages", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=Path("data/db_snapshot.bin"))
    args = parser.parse_args()

    create_snapshot(args.output, args.pages, seed=args.seed)
    print(f"generated snapshot: {args.output} ({args.pages} pages)")


if __name__ == "__main__":
    main()
