---
description: Branch if needed, commit, push and open a PR using the repo template
---
1. If on `main`, create a branch: `feat/`, `fix/` or `chore/` plus a short slug.
2. Run `/verify`. Do not continue on failure.
3. Use the `privacy-reviewer` agent on the staged diff. Do not continue if it finds personal data.
4. Commit with a conventional message (`feat: ...`). Stage files by name, never `git add -A`.
5. Ask before pushing (the repo is public). Then `git push -u origin <branch>` and
   `gh pr create --fill`, and complete What / Why / Schema changes / Testing from `.github/pull_request_template.md`.
