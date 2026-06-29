"""``python -m metronix.memory.freshness`` entry-point."""

from __future__ import annotations

import asyncio

from metronix.memory.freshness.worker import main

if __name__ == "__main__":
    asyncio.run(main())
