# Database

There is no standalone schema here: **the schema lives in the AI engine**, as
SQLAlchemy models with Alembic migrations, under
[`ai-engine/`](../ai-engine/) (package `elysium_engine`). All persistence goes
through SQLAlchemy and a repository layer — no raw SQL in business code.

## SQLite by default, PostgreSQL as a first-class option (ADR-001)

See [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) § ADR-001 for the full
rationale. In short: requiring every desktop user to run a Postgres server
would kill onboarding for the beginner persona, so:

- **Default:** SQLite, a single file in the app data directory. Zero setup,
  trivial backup/snapshot. Vector memory stores embeddings as BLOBs with
  brute-force cosine search (fine at project scale, upgradeable to
  sqlite-vec).
- **Optional / recommended for team & cloud mode:** PostgreSQL with
  **pgvector** for real vector search. Alembic migrations target both
  backends.

## Using PostgreSQL

Point the engine at your server via the `ELYSIUM_DB_URL` environment
variable:

```sh
# pgvector must be available in the target database
ELYSIUM_DB_URL="postgresql+psycopg://elysium:secret@localhost:5432/elysium"
```

Then enable the extension once and run migrations:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

```sh
cd ai-engine
alembic upgrade head
```

When `ELYSIUM_DB_URL` is unset, the engine falls back to the SQLite file in
the app data directory.
