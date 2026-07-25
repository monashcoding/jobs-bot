from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlmodel import SQLModel

from src.backend.sql.tables.base import BaseDB

_log = logging.getLogger(__name__)

T = TypeVar("T", bound=SQLModel)
TDB = TypeVar("TDB", bound=BaseDB)


@dataclass
class CacheEntry(Generic[T]):
    value: T | None
    fetched_at: float
    refreshing: bool = False


class CacheManager(Generic[T]):
    """In-memory stale-while-revalidate cache for BaseDB instances."""

    def __init__(self, db_get: Any, ttl: float = 300.0) -> None:
        self._db_get = db_get  # original unpatched get method
        self._ttl = ttl
        self._store: dict[tuple, CacheEntry[T]] = {}

    def _key(self, pk: tuple) -> tuple:
        return pk if len(pk) > 1 else (pk[0],)

    async def get(self, *pk: Any) -> T | None:
        key = self._key(pk)
        entry = self._store.get(key)

        if entry is None:
            # Cold start - must fetch synchronously
            value = await self._db_get(*pk)
            self._store[key] = CacheEntry(value=value, fetched_at=time.monotonic())
            return value

        # Return cached immediately; refresh in background if stale
        if time.monotonic() - entry.fetched_at > self._ttl and not entry.refreshing:
            entry.refreshing = True
            asyncio.create_task(self._refresh(key, pk))

        return entry.value

    async def _refresh(self, key: tuple, pk: tuple) -> None:
        try:
            value = await self._db_get(*pk)
            self._store[key] = CacheEntry(value=value, fetched_at=time.monotonic())
        except Exception:  # noqa: BLE001
            _log.exception("Background cache refresh failed for %s", key)
            # Keep serving stale data
            if key in self._store:
                self._store[key].refreshing = False

    def put(self, *pk: Any, value: T | None) -> None:
        key = self._key(pk)
        self._store[key] = CacheEntry(value=value, fetched_at=time.monotonic())

    def invalidate(self, *pk: Any) -> None:
        key = self._key(pk)
        self._store.pop(key, None)


def _extract_pk(model: type[SQLModel], instance: SQLModel) -> tuple:
    """Extract primary key values from a SQLModel instance."""
    pk_cols = [col.name for col in model.__table__.primary_key.columns]
    return tuple(getattr(instance, col) for col in pk_cols)


def cached(db: TDB, ttl: float = 300.0) -> TDB:
    """Wrap a BaseDB instance with stale-while-revalidate caching.

    Patches get/upsert/delete on the instance. Custom methods that call
    self.upsert() or self.get() automatically benefit from the cache.
    Returns the same instance with its original type preserved.
    """
    original_get = db.get
    original_upsert = db.upsert
    original_delete = db.delete

    cache = CacheManager(original_get, ttl=ttl)
    db._cache = cache  # type: ignore[attr-defined]

    async def cached_get(*pk: Any) -> Any:
        return await cache.get(*pk)

    async def cached_upsert(instance: Any) -> Any:
        result = await original_upsert(instance)
        pk = _extract_pk(db.model, result)
        cache.put(*pk, value=result)
        return result

    async def cached_delete(*pk: Any) -> bool:
        result = await original_delete(*pk)
        if result:
            cache.invalidate(*pk)
        return result

    db.get = cached_get  # type: ignore[method-assign]
    db.upsert = cached_upsert  # type: ignore[method-assign]
    db.delete = cached_delete  # type: ignore[method-assign]
    return db
