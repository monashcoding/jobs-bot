from __future__ import annotations

from urllib.parse import urlparse

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)


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
        self._client = AsyncIOMotorClient(uri)
        parsed = urlparse(uri)
        db_name = parsed.path.lstrip("/") or "bot"
        self._db = self._client[db_name]

    async def close(self) -> None:
        """Close the Motor client. Call once at shutdown."""
        if self._client:
            self._client.close()

    def collection(self, name: str) -> AsyncIOMotorCollection:
        assert self._db is not None, "MongoDatabase.init() was not called"
        return self._db[name]


mongo = MongoDatabase()
