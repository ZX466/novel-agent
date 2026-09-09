---
name: coding-standards
description: Universal coding and file-organization standards applied to all code changes.
metadata:
  origin: ECC
---

# Coding Standards

## Style

- Small functions (<50 lines), focused files (200-400 typical, 800 max).
- Organization by feature/domain, high cohesion, low coupling.
- No deep nesting (>4 levels), no hardcoded magic values.
- Meaningful names; prefer many small files over few large ones.

## Immutability (critical)

- Never mutate existing objects; create and return new copies.
- Prefer pure functions; avoid side effects.

## Error Handling

- Handle errors at every level; never silently swallow.
- Validate all input at system boundaries (schema-based, fail fast).
- Never trust external data.

## APIs

- Consistent envelope: success flag, data, error message, pagination.

## Repository Pattern

- Data access behind an interface (findAll/findById/create/update/delete).
- Business logic depends on the abstraction, not storage.