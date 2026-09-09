# Kiro — Project Guidance (`.kiro/`)

Project-local files for Kiro. Place the `.kiro/` folder at your project root, or run `.kiro/install.sh <project>` to copy. No global settings are modified.

## Included

- `agents/` — 10 core agents (JSON for CLI + MD for IDE): planner, architect, tdd-guide, code-reviewer, security-reviewer, build-error-resolver, e2e-runner, refactor-cleaner, doc-updater, docs-lookup, loop-operator.
- `skills/` — 12 distilled skills: tdd-workflow, security-review, verification-loop, coding-standards, api-design, backend-patterns, database-migrations, error-handling, deep-research, e2e-testing, git-workflow, strategic-compact.
- `steering/` — always-on rules: development-workflow, coding-style, git-workflow, security, patterns.
- `hooks/` — code-review-on-write, auto-format, console-log-check, doc-file-warning.

## Working Style

1. Plan first (`planner`), then TDD (`tdd-guide`, 80%+ coverage).
2. Review code right after writing (`code-reviewer`); address CRITICAL/HIGH.
3. Security checklist before any commit (no secrets, validate inputs).
4. Conventional commits: `feat|fix|refactor|docs|test|chore|perf|ci`.

## Add skills from ECC

Any additional ECC skill works: copy `skills/<name>/SKILL.md` into `.kiro/skills/<name>/SKILL.md`.