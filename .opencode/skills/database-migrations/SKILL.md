---
name: database-migrations
description: Safe schema/data migration patterns for PostgreSQL, MySQL, and ORMs (Prisma, Drizzle, Django, TypeORM). Zero-downtime, reversible.
metadata:
  origin: ECC
---

# Database Migrations

## When to Activate

- Creating/altering tables, adding/removing columns or indexes
- Data migrations and backfills
- Prefer migrations over manual schema edits

## Principles

- Migrations are code: versioned, reviewed, run in order.
- Always plan rollback; test on a copy of production data.
- Apply structural changes in a way that keeps old and new code working.

## PostgreSQL

- Add column: `ALTER TABLE t ADD COLUMN c type;` — nullable or with default to avoid table rewrite locks.
- Add index without downtime: prefer `CREATE INDEX CONCURRENTLY`.
- Rename column zero-downtime: add new column -> dual-write -> backfill -> switch -> drop old.
- Remove column safely: stop writing first, then drop in a later release.
- Huge data migration: batch in transactions (e.g. 10k rows / batch) with progress tracking.

## ORMs (examples)

- Prisma/Drizzle/Kysely: `npx prisma migrate dev` (dev) / `migrate deploy` (prod).
- Django: `python manage.py makemigrations && migrate`.
- TypeORM: `typeorm migration:run`.
- golang-migrate: `migrate -path migrations up 1`.

## Safety Checklist

- [ ] Migration reversible (down migration present)
- [ ] No SELECT * . Lock-free or concurrent index creation
- [ ] Data batches small enough to avoid long transactions
- [ ] E2E tested against copy of prod schema
- [ ] Backfill verified before flip