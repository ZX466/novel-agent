---
name: tdd-workflow
description: Use when writing new features, fixing bugs, or refactoring. Enforces test-driven development with 80%+ coverage (unit, integration, E2E).
metadata:
  origin: ECC
---

# TDD Workflow

Activate for: new features, bug fixes, refactors, new API endpoints, or continuing from a `*.plan.md`.

## Process (RED -> GREEN -> REFACTOR)

1. **RED**: Write a failing test for the target behavior. Include edge cases and error paths.
2. **GREEN**: Implement the smallest change that passes the test.
3. **REFACTOR**: Clean up while keeping tests green. Verify 80%+ coverage.

## Coverage Rules

- Minimum 80% coverage (unit + integration + E2E).
- Cover edge cases, error scenarios, boundaries.

## Verification Gate

Run before done:

```bash
npm test -- --coverage      # or the project's test runner
npm run build / tsc --noEmit / pyright .
npm run lint / ruff check .
```

Report: total / passed / failed / coverage %. Fix failures before moving on.

## Output Format

```
RED:   <test added>
GREEN: <implementation>
REPORT: X/Y passed, Z% coverage, build/lint/type [PASS/FAIL]
```