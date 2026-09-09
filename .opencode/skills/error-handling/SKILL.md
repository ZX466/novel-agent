---
name: error-handling
description: Robust error handling across TypeScript, Python, and Go. Typed errors, boundaries, retries, circuit breakers, and user-facing messages.
metadata:
  origin: ECC
---

# Error Handling Patterns

## When to Activate

- Designing error types / hierarchy
- Adding retry or circuit-breaker logic
- Handling unreliable external dependencies

## Core Principles

- Handle errors at every level; never swallow silently.
- Fail fast at boundaries; log detailed context server-side; user-friendly messages in UI.
- Never leak internals/secrets in client-facing errors.

## TypeScript

```typescript
class AppError extends Error { constructor(msg: string, public code: string) { super(msg) } }
class NotFoundError extends AppError { constructor(msg: string) { super(msg, 'NOT_FOUND') } }
```

## Python

```python
class AppError(Exception): ...
class NotFoundError(AppError): ...
```

## Retry with Exponential Backoff

- Use for transient failures (network, 5xx), NOT for 4xx.
- maxAttempts≈3, base delay 500ms, cap 10s, add jitter.

## Circuit Breaker

- After N consecutive failures, open the circuit; fail fast for a cooldown, then allow a probe.

## API Error Envelope

```
{ success: false, error: { code, message }, (details?) }
```

## Checklist

- [ ] No unhandled async rejections
- [ ] No silent `catch {}`
- [ ] Retry only transient errors with backoff
- [ ] Error messages scrubbed of internals
- [ ] Every public boundary validates input