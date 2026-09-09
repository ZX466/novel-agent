---
name: e2e-testing
description: Playwright end-to-end testing for critical user flows.
metadata:
  origin: ECC
---

# E2E Testing

Use for critical user flows (signup, checkout, auth, onboarding).

## Process

1. Identify the top 3-5 user journeys to cover.
2. Write a Playwright spec per flow. Use accessible selectors (`getByRole`, `getByLabel`).
3. Cover happy path + key failure states.
4. Run `npx playwright test`; keep suite deterministic (no sleeps, use `expect` retries).

## Structure

- Organize by feature: `e2e/<feature>.spec.ts`.
- Assert user-visible outcomes, not implementation details.
- Tag slow suites (`@slow`) separately from CI-critical ones.

## Gate

- All tests pass headless; record traces on failure for debugging.