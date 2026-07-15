from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from vp_pipeline import DEFAULT_BOOTSTRAP_DAYS, sync_all


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchroniseer lokale Vlaams Parlement-data en exporteer naar Excel."
    )
    parser.add_argument(
        "--since",
        help="Volledige vulling of heropbouw vanaf datum YYYY-MM-DD. Bij expliciete --since wordt de backfill niet beperkt door de vorige sync-state.",
    )
    parser.add_argument(
        "--rolling-days",
        type=int,
        default=45,
        help="Aantal dagen terugkijken bij incrementele updates.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=100,
        help="Maximum aantal zoekpagina's per zoekterm.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bootstrap_since = (
        date.fromisoformat(args.since)
        if args.since
        else date.today() - timedelta(days=DEFAULT_BOOTSTRAP_DAYS)
    )
    result = sync_all(
        bootstrap_since=bootstrap_since,
        rolling_days=args.rolling_days,
        max_pages=args.max_pages,
        force_full_refresh=bool(args.since),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
