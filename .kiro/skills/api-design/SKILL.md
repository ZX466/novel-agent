---
name: api-design
description: REST API design standards: resources, verbs, status codes, validation, pagination, versioning, auth.
metadata:
  origin: ECC
---

# API Design

## Resources & Verbs

- Nouns for resources, standard verbs (GET/POST/PUT/PATCH/DELETE).
- Consistent naming: pluralized resources, kebab/lowercase.

## Status Codes

- 200/201 for success, 400 for client errors, 401/403 auth, 404 missing, 409 conflict, 422 validation, 429 rate limit, 500 server.

## Validation & Errors

- Validate at boundary with schemas; 422 with structured `{field: message}` errors.
- Never leak internals in error bodies.

## Pagination

- Stable cursor or offset pagination; return metadata (total, next).

## Versioning

- Prefix `/v1/` or accept-header versioning; deprecate slowly.

## Auth

- AuthN via tokens, AuthZ per resource; rate-limit sensitive endpoints.

## Response Envelope

`{ success, data, error, pagination }` consistently.