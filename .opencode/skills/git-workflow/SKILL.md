---
name: git-workflow
description: Conventional commits, safe branch/inspection practices, and clean PR hygiene.
metadata:
  origin: ECC
---

# Git Workflow

- Review `git status`, `git diff`, and `git log --oneline -10` before committing.
- Stage only intended files; never commit secrets.
- Conventional commits: `feat|fix|refactor|docs|test|chore|perf|ci(<scope>): subject`.
- No force-push, no bypassing hooks, no empty commits.
- Before a PR: review the full diff against base, include a test plan.

## Safety

- Never `git add -A` blindly. Rebase/interactive only when explicitly requested.
- If hooks reject a commit, fix the underlying issue and make a new commit (don't amend a failed one).