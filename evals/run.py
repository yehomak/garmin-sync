"""
End-to-end eval: Claude answers real questions through the real MCP server, graded against SQL ground truth.

  python -m evals.run --check                    # no model calls: ground truth, graders, tool conversion
  python -m evals.run                            # Messages API (needs ANTHROPIC_API_KEY)
  python -m evals.run --backend claude-code      # headless Claude Code on your Claude login, no API key
  python -m evals.run -k staleness               # one case

Backends:
  api          A minimal tool loop over the Messages API, talking to the server through an in-memory MCP client.
  claude-code  `claude -p` with only this MCP server attached, every built-in tool disabled, run from an empty
               directory so no project CLAUDE.md is loaded. This is the closest thing to a real user's session.

Results go to evals/results/ (gitignored).
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
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

    return grade(case, expected, final_text, called, usage, response.stop_reason if response else None)


def grade(case: Case, expected, final_text: str, called: list[str], usage: dict, stop_reason) -> dict:
    match = ANSWER_RE.findall(final_text)
    answer = match[-1].strip() if match else ""
    used_tool = not case.tools or bool(case.tools & set(called))
    graded_text = final_text if case.grade_full_text else answer
    passed = bool(answer) and used_tool and case.check(graded_text, expected)
    return {
        "id": case.id,
        "passed": passed,
        "expected": expected,
        "answer": answer,
        "tools_called": called,
        "used_required_tool": used_tool,
        "stop_reason": stop_reason,
        "usage": usage,
        "final_text": final_text,
    }


BUILTIN_TOOLS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch", "WebSearch", "Agent", "NotebookEdit"]


def run_case_claude_code(case: Case, workdir: Path, mcp_config: Path) -> dict:
    """One case through headless Claude Code. Parses the stream-json transcript for tool calls."""
    expected = case.truth(lambda q: tools.query_sql(q, path=DEMO_PATH))
    cmd = [
        "claude", "-p", case.question,
        "--append-system-prompt", SYSTEM_SUFFIX.strip(),
        "--mcp-config", str(mcp_config), "--strict-mcp-config",
        "--allowedTools", "mcp__garmin__*",
        "--disallowedTools", *BUILTIN_TOOLS,
        "--no-session-persistence", "--output-format", "stream-json", "--verbose",
    ]  # fmt: skip
    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600)
    called, final_text, usage, models, stop = [], "", {"input_tokens": 0, "output_tokens": 0}, [], None
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_use" and block["name"].startswith("mcp__garmin__"):
                    called.append(block["name"].removeprefix("mcp__garmin__"))
        elif event.get("type") == "result":
            final_text = event.get("result") or ""
            stop = event.get("subtype")
            u = event.get("usage") or {}
            # Claude Code caches its long system prompt, so most input arrives as cache reads and writes.
            cached = u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            usage = {"input_tokens": u.get("input_tokens", 0) + cached, "output_tokens": u.get("output_tokens", 0),
                     "notional_cost_usd": event.get("total_cost_usd")}  # fmt: skip
            models = list(event.get("modelUsage") or {})
    result = grade(case, expected, final_text, called, usage, stop)
    result["models"] = models
    if proc.returncode != 0:
        result["error"] = proc.stderr[-500:]
    return result


def run_claude_code_backend(selected: list[Case]) -> list[dict]:
    if not shutil.which("claude"):
        raise SystemExit("`claude` CLI not found. Install Claude Code, or use --backend api.")
    workdir = Path(tempfile.mkdtemp(prefix="garmin-eval-"))  # empty: no CLAUDE.md, no repo files to peek at
    server = shutil.which("garmin-mcp") or str(Path(__file__).resolve().parent.parent / ".venv/bin/garmin-mcp")
    mcp_config = workdir / "mcp.json"
    mcp_config.write_text(
        json.dumps({"mcpServers": {"garmin": {"command": server, "env": {"GARMIN_DB": str(DEMO_PATH)}}}})
    )
    results = []
    for case in selected:
        print(f"  … {case.id}", flush=True)
        results.append(run_case_claude_code(case, workdir, mcp_config))
    return results


async def main(selected: list[Case], check_only: bool, backend: str = "api") -> int:
    build_demo_db()
    if backend == "claude-code" and not check_only:
        t0 = time.monotonic()
        return report(run_claude_code_backend(selected), "claude-code", t0)
    from garmin_sync.server import mcp  # after GARMIN_DB is set

    async with Client(mcp) as mcp_client:
        api_tools = [to_api_tool(t) for t in (await mcp_client.list_tools()).tools]
        instructions = mcp_client.instructions or ""

        if check_only:
            for case in selected:
                expected = case.truth(lambda q: tools.query_sql(q, path=DEMO_PATH))
                assert expected is not None, f"{case.id}: ground truth is null"
                if case.grade_full_text:
                    assert case.good and case.naive, f"{case.id}: trap cases need good and naive examples"
                    goods = case.good if isinstance(case.good, list) else [case.good]
                    for good in goods:
                        assert case.check(good, expected), f"{case.id}: grader rejects a good example: {good[:60]}"
                    assert not case.check(case.naive, expected), f"{case.id}: grader accepts the naive example"
                else:
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
    return report(results, f"api-{MODEL}", t0)


def regrade(path: Path) -> int:
    """Re-score a saved run with the current graders, without calling the model again."""
    saved = json.loads(path.read_text())
    by_id = {c.id: c for c in CASES}
    results = []
    for r in saved["results"]:
        case = by_id.get(r["id"])
        if case is None:
            continue
        new = grade(case, r["expected"], r["final_text"], r["tools_called"], r["usage"], r["stop_reason"])
        if new["passed"] != r["passed"]:
            print(f"  changed  {r['id']}: {r['passed']} → {new['passed']}")
        results.append(new)
    return report(results, f"{saved.get('backend', 'run')}-regraded", time.monotonic())


def report(results: list[dict], label: str, t0: float) -> int:
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
    out = RESULTS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{label}.json"
    out.write_text(
        json.dumps(
            {"backend": label, "passed": passed, "total": len(results), "results": results}, indent=2, default=str
        )
    )
    print(f"Saved {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Validate cases and tools without calling the API")
    parser.add_argument("-k", help="Run only cases whose id contains this string")
    parser.add_argument("--backend", choices=["api", "claude-code"], default="api")
    parser.add_argument("--regrade", type=Path, metavar="RESULTS_JSON", help="Re-score a saved run, no model calls")
    args = parser.parse_args()
    if args.regrade:
        raise SystemExit(regrade(args.regrade))
    chosen = [c for c in CASES if not args.k or args.k in c.id]
    raise SystemExit(asyncio.run(main(chosen, args.check, args.backend)))
