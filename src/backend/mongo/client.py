from __future__ import annotations

import logging
from typing import Final
from urllib.parse import urlparse

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

_log: Final[logging.Logger] = logging.getLogger(__name__)


class MongoDatabase:
    """Async Motor MongoDB wrapper. Singleton via module-level `mongo`."""

    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None

    async def init(self, uri: str | None) -> None:
        """Initialize Motor client. Call once at startup.

        The database name is taken from the URI path (e.g. mongodb://host/mydb).
        Falls back to "bot" if the URI has no database component.
        """
        if not uri:
            raise ValueError("MONGODB_URI is not set")
        self._client = AsyncIOMotorClient(uri, tz_aware=True)
        parsed = urlparse(uri)
        db_name = parsed.path.lstrip("/")

        if not db_name:
            # Silent misconfiguration otherwise: the scraper takes its database
            # name from a separate variable, so its URI carries no path. Reusing
            # that URI here would connect to an empty database called "bot" and
            # watch a collection that never changes, which is indistinguishable
            # from a quiet job market.
            db_name = "bot"
            _log.warning(
                "MONGODB_URI has no database in its path, falling back to %r. "
                "If jobs never appear, add the database name before the query "
                "string, e.g. mongodb+srv://host/mydb?retryWrites=true",
                db_name,
            )

        self._db = self._client[db_name]
        _log.info("Connected to MongoDB database %r", db_name)

    async def close(self) -> None:
        """Close the Motor client. Call once at shutdown."""
        if self._client:
            self._client.close()
            _log.info("MongoDB client closed")

    def collection(self, name: str) -> AsyncIOMotorCollection:
        assert self._db is not None, "MongoDatabase.init() was not called"
        return self._db[name]


mongo: Final[MongoDatabase] = MongoDatabase()
