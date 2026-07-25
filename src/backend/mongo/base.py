from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any, Generic, TypeVar

from bson import ObjectId

from src.backend.mongo.document import MongoDocument

T = TypeVar("T", bound=MongoDocument)


class BaseCollection(Generic[T]):
    """Abstract base for per-collection classes. Provides generic CRUD + watch()."""

    collection_name: str
    model: type[T]

    def __init__(self, mongo: Any | None = None) -> None:
        self._mongo = mongo

    @property
    def mongo(self) -> Any:
        if self._mongo is not None:
            return self._mongo
        from src.backend.mongo.client import mongo

        return mongo

    def _col(self) -> Any:
        return self.mongo.collection(self.collection_name)

    def _to_doc(self, doc: T) -> dict:
        """Convert model to dict for MongoDB, converting id -> _id as ObjectId."""
        data = doc.model_dump(by_alias=True, exclude_none=True)
        if "_id" in data:
            with suppress(Exception):
                data["_id"] = ObjectId(data["_id"])
        return data

    def _from_raw(self, raw: dict) -> T:
        """Convert a raw MongoDB document to the model type."""
        if "_id" in raw and isinstance(raw["_id"], ObjectId):
            raw["_id"] = str(raw["_id"])
        return self.model.model_validate(raw)

    async def get(self, id: str) -> T | None:
        """Get a document by _id. Returns None if not found or id is invalid."""
        try:
            oid = ObjectId(id)
        except Exception:  # noqa: BLE001
            return None
        raw = await self._col().find_one({"_id": oid})
        if raw is None:
            return None
        return self._from_raw(raw)

    async def upsert(self, doc: T) -> T:
        """Insert a new document (if id is None) or replace an existing one."""
        data = self._to_doc(doc)
        if "_id" not in data:
            result = await self._col().insert_one(data)
            data["_id"] = result.inserted_id
        else:
            await self._col().replace_one({"_id": data["_id"]}, data, upsert=True)
        return self._from_raw(data)

    async def delete(self, id: str) -> bool:
        """Delete a document by _id. Returns True if found and deleted."""
        try:
            oid = ObjectId(id)
        except Exception:  # noqa: BLE001
            return False
        result = await self._col().delete_one({"_id": oid})
        return result.deleted_count > 0

    async def find(self, filter: dict) -> list[T]:
        """Find all documents matching a filter dict."""
        cursor = self._col().find(filter)
        docs = await cursor.to_list(length=None)
        return [self._from_raw(d) for d in docs]

    @asynccontextmanager
    async def watch(
        self,
        pipeline: list[dict] | None = None,
        full_document: str = "updateLookup",
    ) -> AsyncIterator[Any]:
        """Open a change stream on this collection."""
        async with self._col().watch(
            pipeline or [], full_document=full_document
        ) as stream:
            yield stream
