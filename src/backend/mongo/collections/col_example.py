from __future__ import annotations

from pydantic import Field

from src.backend.mongo.base import BaseCollection
from src.backend.mongo.document import MongoDocument


class ExampleDocument(MongoDocument):
    """MongoDB document mirroring the SQL ExampleRecord model."""

    user_id: int
    value: str = Field(default="")


class ExampleDocumentCollection(BaseCollection[ExampleDocument]):
    collection_name = "example_documents"
    model = ExampleDocument

    async def find_by_user_id(self, user_id: int) -> list[ExampleDocument]:
        """Return all documents belonging to a user."""
        return await self.find({"user_id": user_id})


example_document_col = ExampleDocumentCollection()
