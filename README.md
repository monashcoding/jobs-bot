# Discord Bot Template

A reusable Discord bot template using discord.py, SQLModel, and asyncpg. Based on the architecture of [karma-bot](https://github.com/monashcoding/karma-bot).

## Project Structure

```
src/
  bot.py                              # Entry point, error handler, persistent views
  core/
    config.py                         # Project-wide constants and configuration
    checks.py                         # @is_admin() slash command check
    functions/                        # Shared business logic helpers
    message_utils/paginator.py        # Persistent paginated embeds
  backend/
    sql/
      client.py                       # Database singleton (async SQLModel + asyncpg)
      cache.py                        # Stale-while-revalidate cache wrapper
      models.py                       # SQLModel table definitions
      tables/
        base.py                       # BaseDB[T] - generic CRUD (get/upsert/delete)
        db_example.py                 # ExampleRecordDB with get_by_user_id
      schemas/                        # SQL DDL files (create this folder)
        schema_example.sql            # CREATE TABLE IF NOT EXISTS ...
    mongo/
      client.py                       # MongoDatabase singleton (async Motor)
      document.py                     # MongoDocument Pydantic base (_id <-> id)
      base.py                         # BaseCollection[T] - CRUD + watch()
      triggers.py                     # ChangeEvent + ChangeStreamWatcher cog base
      collections/
        col_example.py                # ExampleDocumentCollection
      schemas/                        # MongoDB collection + index definitions (create this folder)
        schema_example.js             # db.createCollection(...), createIndex(...)
  cogs/
    commands/
      general.py                      # /ping
      example.py                      # /example-add, /example-list
    workers/
      example_task.py                 # Hourly background task
      _example_mongo_watcher.py       # Change stream watcher example (inactive; remove _ to enable)
tests/
  conftest.py                         # In-memory SQLite fixtures
  test_base_db.py
  mongo/
    conftest.py                       # mongomock-motor fixtures (no real MongoDB needed)
    test_base_collection.py
```

## Setup

### Prerequisites

- Python 3.12+
- Docker and Docker Compose

### Development

```bash
cp .env.example .env
# Edit .env (DISCORD_TOKEN is required).
# DATABASE_URL is optional: if omitted, a local Postgres container is started automatically.

chmod +x dev.sh
./dev.sh --build
```

`dev.sh` checks `.env` for `DATABASE_URL`:
- **Present** → `docker compose up -d` (uses your external database)
- **Absent** → `docker compose --profile local-db up -d` (starts a bundled `postgres:16-alpine` container at `localhost:5432`)

To run the bot directly (Postgres must already be running and `DATABASE_URL` set):

```bash
pip install -r requirements.txt
python -m src.bot
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Your Discord bot token |
| `DATABASE_URL` | No (dev) | PostgreSQL connection string; omit to use the local-db container |
| `MONGODB_URI` | No | MongoDB connection string (optional; see `src/bot.py`) |

## Testing

Tests use in-memory SQLite and mongomock-motor. No real database setup required.

```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

## Architecture

- **SQLModel** - typed models that double as Pydantic and SQLAlchemy
- **asyncpg** - async PostgreSQL driver
- **BaseDB[T]** - generic CRUD base class; per-table classes add domain methods
- **cached()** - stale-while-revalidate wrapper for any BaseDB instance
- **Motor** - async MongoDB driver; `MongoDatabase` mirrors the SQL `Database` singleton
- **BaseCollection[T]** - generic MongoDB CRUD + `watch()` change stream context manager
- **ChangeStreamWatcher** - cog base class for reacting to MongoDB change streams with auto-reconnect
- **`src/backend/sql/schemas/`** - raw SQL DDL files (`schema_<name>.sql`) with `CREATE TABLE IF NOT EXISTS` statements. Kept alongside the SQLModel definitions as the authoritative reference for the physical schema.
- **`src/backend/mongo/schemas/`** - MongoDB collection and index definition scripts (`schema_<name>.js`) with `db.createCollection()` and `createIndex()` calls. Create these folders when your project needs them.
- **Singleton pattern** - `from src.backend.sql.tables import example_record` and use directly
- **Persistent paginator** - embed buttons survive bot restarts via `PersistentPaginatorView`
- **Cog auto-loading** - all `.py` files in `src/cogs/commands/` and `src/cogs/workers/` load automatically (files prefixed with `_` are skipped)

## Adding a New Feature

### SQL

1. Add a model to `src/backend/sql/models.py`
2. Create `src/backend/sql/tables/db_<name>.py` extending `BaseDB`
3. Export from `src/backend/sql/tables/__init__.py` and `src/backend/sql/__init__.py`
4. Add a `src/backend/sql/schemas/schema_<name>.sql` with the `CREATE TABLE IF NOT EXISTS` DDL (create the folder if it doesn't exist)
5. Create a cog in `src/cogs/commands/<name>.py` with a `setup(bot)` function
6. Add tests in `tests/test_<name>.py` using the `test_db` fixture

### MongoDB

1. Add a document model to `src/backend/mongo/collections/col_<name>.py` extending `MongoDocument`
2. Create a collection class extending `BaseCollection[YourDocument]`
3. Export from `src/backend/mongo/collections/__init__.py`
4. Add a `src/backend/mongo/schemas/schema_<name>.js` with `db.createCollection()` and any index definitions (create the folder if it doesn't exist)
5. Optionally create a `ChangeStreamWatcher` cog in `src/cogs/workers/<name>_watcher.py`
6. Add tests in `tests/mongo/test_<name>.py` using the `example_col` fixture as a reference

## Contributing

1. Fork the repository and create a branch from `main`
2. Install dependencies and set up pre-commit hooks:
   ```bash
   pip install -r requirements.txt
   pre-commit install --hook-type commit-msg
   ```
3. Make your changes and ensure tests and linting pass:
   ```bash
   python -m pytest tests/ -v
   ruff check .
   ```
4. Commit using [Conventional Commits](https://www.conventionalcommits.org) (enforced by pre-commit)
5. Open a pull request against `main`

> **Linting:** This project uses [Ruff](https://docs.astral.sh/ruff/) for linting and import sorting. CI will fail if `ruff check .` reports any errors. Run it locally before pushing.

## Deployment

Tag a release to trigger the Docker build and push to GitHub Container Registry:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Production uses `docker-compose.prod.yml`, which adds a managed Postgres service, `restart: always`, log rotation, and injects `DATABASE_URL` from the host environment:

```bash
POSTGRES_PASSWORD=<secret> docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
