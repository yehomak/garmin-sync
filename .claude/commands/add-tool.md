---
description: Add an MCP tool the right way (query layer, server wrapper, tests, eval case)
argument-hint: <the question the tool should answer>
---
Add an MCP tool that answers: $ARGUMENTS

First check whether `query_sql` plus a better `describe_schema` comment already covers it. A new tool earns its
place only if it encodes judgment the model would otherwise get wrong (anchoring, caveats, derived fields).

1. `garmin_sync/tools.py`: a plain function taking `path=None`, returning a dict. Spread `**_freshness(con)` into the
   result, anchor windows with `_window()`, and put caveats in `notes`.
2. `garmin_sync/server.py`: a thin `@mcp.tool(annotations=READ_ONLY)` wrapper. The docstring is the model's only
   documentation: say *when* to use it and what the output means.
3. `tests/test_tools.py`: test against the `demo_db` fixture. Add the name to `EXPECTED_TOOLS` in `tests/test_server.py`.
4. `evals/cases.py`: add a case whose ground truth is computed by SQL, so the eval proves the model actually picks
   the tool for that question.
5. Update the tool table in `docs/MCP.md`, then run `/verify`.
