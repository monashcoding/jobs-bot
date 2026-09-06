from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Final

from bson import ObjectId
from pydantic import BaseModel, Field, field_validator

from src.backend.mongo.base import BaseCollection
from src.backend.mongo.document import MongoDocument

_log: Final[logging.Logger] = logging.getLogger(__name__)


class Company(BaseModel):
    name: str = Field(default="")
    website: str | None = Field(default=None)
    logo: str | None = Field(default=None)


class JobDocument(MongoDocument):
    fingerprint: str | None = Field(default=None)
    application_url: str | None = Field(default=None)
    board_eligible: bool | None = Field(default=None)
    board_score: int | None = Field(default=None)
    close_date: datetime | None = Field(default=None)
    company: Company = Field(default_factory=Company)
    company_tier: str | None = Field(default=None)
    created_at: datetime | None = Field(default=None)
    days_lived: int | None = Field(default=None)
    description: str | None = Field(default=None)
    discipline: str | None = Field(default=None)
    industry_field: str | None = Field(default=None)
    is_sponsored: bool = Field(default=False)
    locations: list[str] = Field(default_factory=list)
    one_liner: str | None = Field(default=None)
    outdated: bool = Field(default=False)
    source: str | None = Field(default=None)
    source_urls: list[str] = Field(default_factory=list)
    study_fields: list[str] = Field(default_factory=list)
    title: str = Field(default="Untitled")
    type: str | None = Field(default=None)
    updated_at: datetime | None = Field(default=None)
    version: str | None = Field(default=None)
    wfh_status: str | None = Field(default=None)
    working_rights: list[str] = Field(default_factory=list)

    @field_validator(
        "locations", "source_urls", "study_fields", "working_rights", mode="before"
    )
    @classmethod
    def coerce_none_to_list(cls, v: Any) -> list:
        return v if v is not None else []


class JobDocumentCollection(BaseCollection[JobDocument]):
    collection_name = "active_jobs"
    model = JobDocument

    async def get_many(self, ids: list[str]) -> dict[str, JobDocument]:
        """Return the documents for *ids*, keyed by id, skipping any not found.

        One query for a whole board's worth of posts. The reconciliation
        commands work from JobPost records and need the document behind each one
        to recompute its tags; fetching them singly is a round trip per thread,
        which on a full board is thousands of them.

        Ids that are not valid ObjectIds are dropped rather than raising. They
        come from the SQL side, where nothing constrains their shape, and one
        malformed row should not take down a reconciliation over every other.
        """
        oids: list[ObjectId] = []
        for id in ids:
            try:
                oids.append(ObjectId(id))
            except Exception:  # noqa: BLE001
                _log.warning("Skipping malformed job id %r", id)
                continue

        if not oids:
            return {}

        raw = await self._col().find({"_id": {"$in": oids}}).to_list(None)
        docs = [self._from_raw(d) for d in raw]
        return {doc.id: doc for doc in docs if doc.id}


job_col: Final[JobDocumentCollection] = JobDocumentCollection()
