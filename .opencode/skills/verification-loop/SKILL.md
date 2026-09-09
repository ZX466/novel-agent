---
name: verification-loop
description: Run before PR / after features. Full quality gate: build, types, lint, tests, security, diff review.
metadata:
  origin: ECC
---

# Verification Loop

Use after a feature/refactor and before creating a PR.

## Phases

1. **Build** — `npm run build` / `pnpm build`; stop if it fails.
2. **Types** — `tsc --noEmit` / `pyright .`.
3. **Lint** — `npm run lint` / `ruff check .`.
4. **Tests** — `npm test -- --coverage`; target 80%, report counts.
5. **Security** — grep for `sk-`, `api_key`, secrets; check for leaky errors.
6. **Diff** — `git diff --stat`; review each changed file for unintended changes, missing error handling, edge cases.

## Output Report

```
VERIFICATION REPORT
Build:     [PASS/FAIL]
Types:     [PASS/FAIL] (X)
Lint:      [PASS/FAIL] (X)
Tests:     [PASS/FAIL] (X/Y, Z% cov)
Security:  [PASS/FAIL] (X)
Diff:      [X files]

Overall:   [READY/NOT READY]
Issues: ...
```