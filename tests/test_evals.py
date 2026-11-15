"""The eval loop itself, with a scripted fake Anthropic client: no network, no tokens."""

from types import SimpleNamespace as NS

import pytest
from mcp.client import Client

from evals import run
from evals.cases import CASES
from garmin_sync import tools
from garmin_sync.server import mcp


class ScriptedClaude:
    """Replays fixed responses: first a tool call, then a final answer."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = NS(messages=NS(create=self._create))

    async def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


def _usage():
    return NS(input_tokens=100, output_tokens=20)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("answer_offset, should_pass", [(0, True), (5, False)])
async def test_run_case_loop_grades_against_ground_truth(demo_env, monkeypatch, answer_offset, should_pass):
    monkeypatch.setattr(run, "DEMO_PATH", demo_env)
    case = next(c for c in CASES if c.id == "manual_sessions_28d")
    expected = case.truth(lambda q: tools.query_sql(q, path=demo_env))

    claude = ScriptedClaude(
        [
            NS(
                stop_reason="tool_use",
                usage=_usage(),
                content=[NS(type="tool_use", id="t1", name="get_training_log", input={"days": 28})],
            ),
            NS(
                stop_reason="end_turn",
                usage=_usage(),
                content=[NS(type="text", text=f"Checked the log.\nANSWER: {expected + answer_offset}")],
            ),
        ]
    )
    async with Client(mcp) as mcp_client:
        api_tools = [run.to_api_tool(t) for t in (await mcp_client.list_tools()).tools]
        result = await run.run_case(claude, mcp_client, api_tools, "instr", case)

    assert result["passed"] is should_pass
    assert result["tools_called"] == ["get_training_log"]
    assert result["usage"] == {"input_tokens": 200, "output_tokens": 40}
    # the second request carries the tool result back, matched by id
    sent = claude.requests[1]["messages"]  # the loop's own list, so it also holds the final turn
    tool_result = next(m for m in sent if m["role"] == "user" and isinstance(m["content"], list))["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "t1"
    assert '"sessions"' in tool_result["content"]


@pytest.mark.anyio
async def test_answer_without_required_tool_fails(demo_env, monkeypatch):
    monkeypatch.setattr(run, "DEMO_PATH", demo_env)
    case = next(c for c in CASES if c.id == "manual_sessions_28d")
    expected = case.truth(lambda q: tools.query_sql(q, path=demo_env))
    claude = ScriptedClaude(
        [
            NS(stop_reason="end_turn", usage=_usage(), content=[NS(type="text", text=f"ANSWER: {expected}")]),
        ]
    )
    async with Client(mcp) as mcp_client:
        result = await run.run_case(claude, mcp_client, [], "instr", case)
    assert result["passed"] is False
    assert result["used_required_tool"] is False
