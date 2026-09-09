---
name: security-review
description: Use when adding auth, handling user input, working with secrets, creating API endpoints, or payment/sensitive features. Security checklist and patterns.
metadata:
  origin: ECC
---

# Security Review

Activate for: authentication, user input/file uploads, new API endpoints, secrets, payments, sensitive data, third-party integrations.

## Checklist

### 1. Secrets
- No hardcoded keys/passwords. Use env vars, fail fast if missing.
- `.env.local` in `.gitignore`; no secrets in git history.

### 2. Input Validation
- Zod/schema validation on all boundaries. Reject invalid input early.

### 3. Injection
- Parameterized queries only (no string-built SQL).
- Sanitize/escape HTML output (XSS).
- Use ORM/SQLAlchemy/Prisma etc., never raw concatenation.

### 4. Auth
- Verify authn/authz on every protected route.
- Rate limiting on auth/endpoints; secure session handling.

### 5. Errors & Data
- Error messages never leak internals/secrets.
- Follow least-privilege for tokens and file access.

## Verification

- [ ] No hardcoded secrets
- [ ] All inputs validated
- [ ] No injection sinks
- [ ] Authz checked on sensitive paths
- [ ] Errors scrubbed

## Actions

If a vulnerability is found: STOP -> use `security-reviewer` agent -> fix CRITICAL first -> rotate exposed secrets -> scan for similar patterns.