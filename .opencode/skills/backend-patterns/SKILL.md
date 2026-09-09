---
name: backend-patterns
description: Backend/API development patterns: REST structure, repository/service/middleware layers, query optimization, N+1 prevention, transactions, caching, auth.
metadata:
  origin: ECC
---

# Backend Patterns

## When to Activate

- Building a new API endpoint or service layer
- Optimizing slow queries, adding caching, or auth

## API / Layering

- Route -> controller -> service -> repository pattern; keep business logic out of controllers.
- Middleware for cross-cutting concerns (auth, logging, validation, rate limit).
- Consistent response envelope: `{ success, data, error, pagination }`.

## Database

- Fix N+1: eager-load relations (Prisma `include`, Django `select_related`/`prefetch_related`, SQLAlchemy `joinedload`).
- Index columns used in WHERE/JOIN/ORDER BY; avoid wrapping indexed columns in functions.
- Use transactions for multi-step writes (`BEGIN/COMMIT/ROLLBACK`, `@transaction.atomic`, `with session.begin()`).
- Batch inserts for bulk data.

## Caching

- Cache-aside: read cache -> miss -> query DB -> set cache (TTL). Invalidate on write.
- Never cache per-user data without keying by user.
- Short TTL + stale-while-revalidate for hot reads.

## AuthN/AuthZ

- Validate JWT signature + expiry; load claims; enforce role/middleware per route.
- Never trust client-provided user id or role.
- Rate limit auth and public endpoints.

## Checklist

- [ ] Controllers thin, services fat
- [ ] No N+1 queries
- [ ] Writes inside transactions
- [ ] Cache invalidation on mutation
- [ ] AuthZ checked server-side on every sensitive path