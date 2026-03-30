#!/usr/bin/env python3
"""Process unsynced documents for graph extraction from PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "src")

from metatron.core.config import Settings
from metatron.ingestion.pipeline import process_unsynced_graphs
from metatron.storage.postgres import PostgresStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Process unsynced documents for graph extraction")
    parser.add_argument("--workspace", default="MTRNIX", help="Workspace ID (default: MTRNIX)")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size (default: 50)")
    args = parser.parse_args()

    s = Settings()
    store = PostgresStore(s.postgres_dsn)
    result = asyncio.run(process_unsynced_graphs(args.workspace, store, args.batch_size))
    print(
        f"Graph processing: {result['ok']} ok, "
        f"{result['errors']} errors, "
        f"{result['skipped']} skipped"
    )


if __name__ == "__main__":
    main()
