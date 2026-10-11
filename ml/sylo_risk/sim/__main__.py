from __future__ import annotations

import argparse
from pathlib import Path

from .generator import SEEDS, default_output_dir, write_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate seeded synthetic FR-GH payments")
    parser.add_argument("--seed", required=True, choices=SEEDS)
    parser.add_argument("--small", action="store_true", help="generate 20,000 rows for tests")
    parser.add_argument("--out", type=Path, default=default_output_dir())
    args = parser.parse_args()
    path = write_dataset(args.seed, args.small, args.out)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
