"""``python -m metatron.memory.freshness`` entry-point."""

from __future__ import annotations

import asyncio

from metatron.memory.freshness.worker import main

if __name__ == "__main__":
    asyncio.run(main())
