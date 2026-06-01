"""Tool-result round appends entity memories (MTRNIX-372 P4).

Integration test — requires Postgres + Neo4j. Stub for now.
"""

import pytest

pytestmark = pytest.mark.integration


async def test_tool_result_appends_memory() -> None:
    pytest.skip(
        "Adapt from test_proxy_e2e.py: (1) create proxy agent; (2) store a memory "
        "ABOUT a known entity for that agent; (3) send a request whose tail message "
        "is role=tool mentioning that entity; (4) assert the upstream received the "
        "appended memory in <relevant_memories> and proxy.tool_result_enrichment.applied "
        "is in the activity for the correlation_id."
    )
