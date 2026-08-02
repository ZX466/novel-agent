# Project Agent Instructions

## Principles

- Verify repository evidence before acting; do not guess APIs, behavior, dependencies, or configuration.
- Make the smallest precise change that meets the request. Avoid unrelated refactors, speculative abstractions, and unnecessary dependencies.
- Plan before implementing complex, cross-module, architectural, ambiguous, or security-sensitive work.
- Prefer immutable updates. Follow existing project conventions for structure, naming, validation, logging, and error handling.
- Validate all external input at trust boundaries. Never expose, log, commit, or copy secrets, tokens, private keys, or `.env` contents.
- After changes, run relevant tests, lint, type checks, build, and/or security checks. State explicitly when verification cannot run.

## Architecture Notes

- **task_type routing**: Frontend injects `[task:TYPE]` markers (outline/generate/continue/rewrite/polish). Backend `_extract_task_type()` parses them and `build_pipeline_for_task()` constructs a minimal graph.
- **True streaming**: draft_node/refine_node use `stream=True` + `on_token` callback → asyncio.Queue → `stream_pipeline` yields tokens real-time. Do NOT revert to the old 4-char chunking approach.
- **Stage fallback**: evaluate_node catches failures and returns `fallback_mode=True, score=0.5`. Pipeline continues to safety_check instead of crashing.
- **BYOK presets**: Frontend `BYOK_PRESETS` in `types.ts` + backend `byok_presets` in `config.py`. Users click a preset to auto-fill api_base/model.

## Workflow

1. For complex work, define scope, dependencies, risks, and an implementation plan.
2. For features and bug fixes, write or update a failing test first where practical; implement the minimum fix; then refactor.
3. Review completed changes for correctness, edge cases, regressions, maintainability, and security.
4. Record durable project knowledge only in existing project documentation. Do not create new top-level docs or duplicate information without a clear need.
5. Use Conventional Commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, or `ci:`.

## Quality And Security

- Keep functions focused, files cohesive, nesting shallow, identifiers clear, and errors handled explicitly.
- Use parameterized database queries, output sanitization, authorization checks, CSRF protection where applicable, and non-sensitive error messages.
- Before committing sensitive changes, inspect authentication, authorization, input validation, data exposure, rate limits, and injection risks.
- If a critical security issue or exposed secret is found: stop, remediate it, rotate the secret, and check for similar occurrences.

## ECC Usage

Use specialized agents only when they add value:

- `planner`: complex features or refactors
- `architect`: system design or major technical decisions
- `tdd-guide`: new behavior and bug fixes
- `code-reviewer`: implementation review
- `security-reviewer`: auth, permissions, secrets, payments, public APIs, or untrusted input
- Language/build/database specialists: only for relevant stack-specific review or failures

Use skills as the primary workflow surface. Treat legacy slash commands as compatibility shims.

## Completion Criteria

- Requirements are met with a minimal maintainable change.
- Relevant tests and checks pass; aim for 80%+ coverage where the project measures coverage.
- Known limitations, skipped checks, and remaining risks are clearly reported.
