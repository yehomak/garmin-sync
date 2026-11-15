"""The MCP surface, exercised through a real in-memory MCP client."""

import json

import pytest
from mcp.client import Client

from garmin_sync.server import mcp

EXPECTED_TOOLS = {
    "describe_schema",
    "get_snapshot",
    "get_sleep_trend",
    "get_recovery_trend",
    "get_training_log",
    "get_day",
    "compare_periods",
    "query_sql",
    "get_profile",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_tools_are_listed_and_all_read_only(demo_env):
    async with Client(mcp) as client:
        listed = (await client.list_tools()).tools
    assert {t.name for t in listed} == EXPECTED_TOOLS
    for t in listed:
        assert t.description, f"{t.name} has no description"
        assert t.annotations and t.annotations.read_only_hint, f"{t.name} is not marked read-only"


@pytest.mark.anyio
async def test_call_tool_end_to_end(demo_env):
    async with Client(mcp) as client:
        result = await client.call_tool("get_sleep_trend", {"days": 7})
    payload = json.loads(result.content[0].text)
    assert payload["to"] == "2026-03-31"
    assert payload["nights"] >= 5


@pytest.mark.anyio
async def test_server_ships_instructions_and_review_prompt(demo_env):
    async with Client(mcp) as client:
        prompts = (await client.list_prompts()).prompts
        assert "data_through" in (client.instructions or "")
    assert [p.name for p in prompts] == ["weekly_review"]
