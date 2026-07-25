from __future__ import annotations

from sqlmodel import select

from src.backend.sql.models import ExampleRecord
from src.backend.sql.tables.base import BaseDB


class ExampleRecordDB(BaseDB[ExampleRecord]):
    model = ExampleRecord

    async def get_by_user_id(self, user_id: int) -> list[ExampleRecord]:
        """Return all records belonging to a user."""
        async with self._session() as s:
            result = await s.exec(
                select(ExampleRecord).where(ExampleRecord.user_id == user_id)
            )
            return list(result.all())


example_record = ExampleRecordDB()
