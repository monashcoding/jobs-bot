from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MongoDocument(BaseModel):
    """Base class for MongoDB documents. Maps _id <-> id and allows both aliases."""

    id: str | None = Field(default=None, alias="_id")
    model_config = ConfigDict(populate_by_name=True)
