#!/usr/bin/env python3
"""Watch LongMemEval benchmark progress from a JSONL results file."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def count_completed(path: Path) -> tuple[int, str | None, float | None]:
    if not path.exists():
        return 0, None, None
    count = 0
    last_id: str | None = None
    mtime = path.stat().st_mtime
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            count += 1
            last_id = entry.get("question_id")
    return count, last_id, mtime


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor LongMemEval JSONL progress")
    parser.add_argument("results_file", help="Path to results JSONL")
    parser.add_argument("--total", type=int, default=0, help="Expected total questions")
    parser.add_argument("--interval", type=float, default=5.0, help="Refresh interval in seconds")
    parser.add_argument("--once", action="store_true", help="Print once and exit")
    args = parser.parse_args()

    path = Path(args.results_file)
    previous_count = -1
    start_time = time.time()

    while True:
        count, last_id, mtime = count_completed(path)
        total = args.total or max(count, 1)
        pct = (count / total * 100) if total else 0.0
        updated = (
            datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            if mtime is not None
            else "n/a"
        )

        elapsed = time.time() - start_time
        rate = count / elapsed if elapsed > 0 and count > 0 else 0.0
        remaining = total - count
        eta_seconds = remaining / rate if rate > 0 else None
        eta_text = f"{eta_seconds / 60:.1f} min" if eta_seconds is not None else "n/a"

        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] "
            f"completed={count}/{total} ({pct:.1f}%) "
            f"last={last_id or 'n/a'} "
            f"updated={updated} "
            f"eta={eta_text}",
            flush=True,
        )

        if args.once or (args.total and count >= args.total):
            break
        if count == previous_count and args.once:
            break
        previous_count = count
        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
