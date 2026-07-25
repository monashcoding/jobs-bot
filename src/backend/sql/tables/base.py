from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

T = TypeVar("T", bound=SQLModel)


class BaseDB(Generic[T]):
    """Abstract base for per-table DB classes. Provides generic CRUD."""

    model: type[T]

    def __init__(self, db: Any | None = None) -> None:
        self._db = db

    @property
    def db(self) -> Any:
        if self._db is not None:
            return self._db
        from src.backend.sql.client import db

        return db

    def _session(self) -> AsyncSession:
        return self.db.session()

    async def get(self, *pk: Any) -> T | None:
        """Get a record by primary key (single or composite)."""
        async with self._session() as s:
            return await s.get(self.model, pk if len(pk) > 1 else pk[0])

    async def upsert(self, instance: T) -> T:
        """Insert or update a record."""
        async with self._session() as s:
            merged = await s.merge(instance)
            await s.commit()
            await s.refresh(merged)
            return merged

    async def delete(self, *pk: Any) -> bool:
        """Delete a record by primary key. Returns True if found and deleted."""
        async with self._session() as s:
            obj = await s.get(self.model, pk if len(pk) > 1 else pk[0])
            if obj:
                await s.delete(obj)
                await s.commit()
                return True
            return False
