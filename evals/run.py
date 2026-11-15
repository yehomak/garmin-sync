"""
End-to-end eval: Claude answers real questions through the real MCP server, graded against SQL ground truth.

  python -m evals.run --check        # no API calls: builds the demo DB, computes ground truth, converts tools
  python -m evals.run                # full run (needs ANTHROPIC_API_KEY; costs a few cents per case)
  python -m evals.run -k staleness   # one case

The model talks to the same MCPServer a Claude Code user gets (tool descriptions and server
instructions included), over an in-memory MCP client. Results go to evals/results/ (gitignored).
"""

import argparse
import asyncio
import json
import os
import re
import time
from datetime import date, timedelta
from pathlib import Path

from mcp.client import Client

from evals.cases import CASES, Case
from garmin_sync import demo, tools

MODEL = "claude-opus-5-5"
MAX_TURNS = 8
RESULTS_DIR = Path(__file__).parent / "results"
DEMO_PATH = Path(__file__).parent / "results" / "eval-demo.duckdb"
ANSWER_RE = re.compile(r"^ANSWER:\s*(.+)$", re.MULTILINE)

SYSTEM_SUFFIX = (
    "\n\nYou are answering a question about the user's own data. Use the tools; do not guess numbers. "
    "Finish with one final line in the form `ANSWER: <short answer>`."
)


def build_demo_db() -> Path:
    """Demo data ending 4 days ago, so the staleness case has a real answer."""
    DEMO_PATH.parent.mkdir(exist_ok=True)
    demo.build(DEMO_PATH, end=date.today() - timedelta(days=4))
    os.environ["GARMIN_DB"] = str(DEMO_PATH)
    return DEMO_PATH


def to_api_tool(t) -> dict:
    """MCP tool → Messages API tool definition."""
    return {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}


async def run_case(client, mcp_client: Client, api_tools: list[dict], instructions: str, case: Case) -> dict:
    expected = case.truth(lambda q: tools.query_sql(q, path=DEMO_PATH))
    messages = [{"role": "user", "content": case.question}]
    called: list[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0}
    final_text = ""
    response = None

    for _ in range(MAX_TURNS):
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=instructions + SYSTEM_SUFFIX,
            tools=api_tools,
            messages=messages,
            # Opus 5.5 can decline on safety classifiers; route to a fallback model instead of failing the case.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        messages.append({"role": "assistant", "content": response.content})  # keep thinking blocks intact

        if response.stop_reason in ("end_turn", "refusal", "max_tokens"):
            final_text = "".join(b.text for b in response.content if b.type == "text")
            break
        if response.stop_reason == "pause_turn":
            continue

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            called.append(block.name)
            out = await mcp_client.call_tool(block.name, block.input)
            text = "\n".join(c.text for c in out.content if getattr(c, "type", "") == "text")
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text, "is_error": out.is_error})
        messages.append({"role": "user", "content": results})

    match = ANSWER_RE.findall(final_text)
    answer = match[-1].strip() if match else ""
    used_tool = not case.tools or bool(case.tools & set(called))
    passed = bool(answer) and used_tool and case.check(answer, expected)
    return {
        "id": case.id,
        "passed": passed,
        "expected": expected,
        "answer": answer,
        "tools_called": called,
        "used_required_tool": used_tool,
        "stop_reason": response.stop_reason if response else None,
        "usage": usage,
        "final_text": final_text,
    }


async def main(selected: list[Case], check_only: bool) -> int:
    build_demo_db()
    from garmin_sync.server import mcp  # after GARMIN_DB is set

    async with Client(mcp) as mcp_client:
        api_tools = [to_api_tool(t) for t in (await mcp_client.list_tools()).tools]
        instructions = mcp_client.instructions or ""

        if check_only:
            for case in selected:
                expected = case.truth(lambda q: tools.query_sql(q, path=DEMO_PATH))
                assert expected is not None, f"{case.id}: ground truth is null"
                rendered = (
                    {True: "yes", False: "no"}.get(expected, expected) if isinstance(expected, bool) else expected
                )
                assert case.check(f"{rendered}", expected), f"{case.id}: check rejects its own ground truth"
                print(f"  ok  {case.id:26} expected={expected}")
            print(f"{len(selected)} cases valid, {len(api_tools)} tools converted. No API calls made.")
            return 0

        import anthropic  # only needed for real runs

        client = anthropic.AsyncAnthropic()
        t0 = time.monotonic()
        results = [await run_case(client, mcp_client, api_tools, instructions, c) for c in selected]

    passed = sum(r["passed"] for r in results)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(
            f"  {mark}  {r['id']:26} expected={r['expected']!s:12} "
            f"answer={r['answer'][:50]!r}  tools={r['tools_called']}"
        )
    tokens_in = sum(r["usage"]["input_tokens"] for r in results)
    tokens_out = sum(r["usage"]["output_tokens"] for r in results)
    print(
        f"\n{passed}/{len(results)} passed · {tokens_in:,} in / {tokens_out:,} out tokens "
        f"· {time.monotonic() - t0:.0f}s"
    )

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{MODEL}.json"
    out.write_text(
        json.dumps({"model": MODEL, "passed": passed, "total": len(results), "results": results}, indent=2, default=str)
    )
    print(f"Saved {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Validate cases and tools without calling the API")
    parser.add_argument("-k", help="Run only cases whose id contains this string")
    args = parser.parse_args()
    chosen = [c for c in CASES if not args.k or args.k in c.id]
    raise SystemExit(asyncio.run(main(chosen, args.check)))
