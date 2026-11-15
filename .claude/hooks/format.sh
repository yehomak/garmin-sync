#!/usr/bin/env bash
# PostToolUse hook: format and lint-fix any Python file Claude just wrote.
# Formatting is the hook's job, not the model's, so diffs stay about behaviour.
f=$(jq -r '.tool_input.file_path // empty')
case "$f" in
  *.py)
    "$CLAUDE_PROJECT_DIR/.venv/bin/ruff" format -q "$f"
    "$CLAUDE_PROJECT_DIR/.venv/bin/ruff" check --fix -q "$f" || true
    ;;
esac
exit 0
