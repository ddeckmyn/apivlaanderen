from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from member_ai_overviews import active_store_dir, write_member_ai_overviews


def main() -> None:
    store_dir = active_store_dir()
    output_path = write_member_ai_overviews(store_dir=store_dir)
    print(f"Wrote AI overviews to {output_path}")


if __name__ == "__main__":
    main()
