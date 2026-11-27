---
name: sql-migration
version: 0.1.0
description: Change a database schema without downtime or data loss
tools: [bash, file.read, file.write, file.edit, search.text]
---

# Write a schema migration

Migrations run once, against data you cannot see, and cannot be un-run in
production. Treat every one as irreversible.

1. Read the current schema and the migration tool's conventions before writing.
2. Write the forward migration and the rollback together. If you cannot write
   the rollback, you do not understand the change.
3. Expand, migrate, contract — three deploys, never one:
   add the new column (nullable) → backfill in batches → switch reads →
   stop writing the old column → drop it in a later release.
4. Never take a table lock on a hot table: no `ALTER ... SET NOT NULL`
   without a validated constraint, no `ADD COLUMN ... DEFAULT now()` on
   Postgres < 11.
5. Backfill in batches with a bound, and log progress. One `UPDATE` over a
   million rows is an outage.
6. Add the index concurrently.
7. Test against a copy of production-shaped data, and time it.
8. Ship the rollback plan in the migration description, not in your head.
