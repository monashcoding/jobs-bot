from __future__ import annotations

import logging
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

_log: Final[logging.Logger] = logging.getLogger(__name__)


# Columns added to tables that predate them. Keep each ADD COLUMN IF NOT EXISTS
# and nullable, so applying them to an existing deployment cannot fail or need a
# backfill.
_ADDITIVE_COLUMNS: Final[tuple[str, ...]] = (
    "ALTER TABLE job_guild_configs ADD COLUMN IF NOT EXISTS intern_recap_channel_id BIGINT",
    "ALTER TABLE job_guild_configs ADD COLUMN IF NOT EXISTS grad_recap_channel_id BIGINT",
)


class Database:
    """Async SQLAlchemy/SQLModel database wrapper. Singleton via module-level `db`."""

    def __init__(self) -> None:
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None

    async def init(self, dsn: str | None) -> None:
        """Initialize engine and create tables. Call once at startup."""
        if not dsn:
            raise ValueError("DATABASE_URL is not set")
        if dsn.startswith("postgresql://"):
            dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
        _log.info("Connecting to SQL database")
        self._engine = create_async_engine(dsn, pool_size=5, max_overflow=5)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            await self._add_missing_columns(conn)
        _log.info("SQL database ready")

    @staticmethod
    async def _add_missing_columns(conn) -> None:
        """Add columns introduced after a table was first created.

        SQLModel.metadata.create_all only creates missing *tables*; it never
        alters an existing one. A new field on an existing model therefore does
        not reach a deployed database, and every read of that table fails on the
        missing column. These statements are idempotent, so they are safe to run
        on every start, and this stays a reasonable substitute for a migration
        tool only while the changes are additive and nullable.
        """
        for statement in _ADDITIVE_COLUMNS:
            await conn.execute(text(statement))

    async def close(self) -> None:
        """Dispose of the connection pool. Call once at shutdown."""
        if self._engine:
            await self._engine.dispose()
            _log.info("SQL connection pool closed")

    @property
    def engine(self) -> AsyncEngine:
        assert self._engine is not None, "Database.init() was not called"
        return self._engine

    def session(self) -> AsyncSession:
        """Create a new async session. Use as `async with db.session() as s:`."""
        assert self._session_factory is not None, "Database.init() was not called"
        return self._session_factory()


db: Final[Database] = Database()
