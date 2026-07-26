from __future__ import annotations

from datetime import datetime
from typing import Final

from pydantic import BaseModel, Field

from src.backend.mongo.base import BaseCollection
from src.backend.mongo.document import MongoDocument


class Company(BaseModel):
    name: str = Field(default="")
    website: str | None = Field(default=None)
    logo: str | None = Field(default=None)


class JobDocument(MongoDocument):
    fingerprint: str | None = Field(default=None)
    application_url: str | None = Field(default=None)
    close_date: datetime | None = Field(default=None)
    company: Company = Field(default_factory=Company)
    created_at: datetime | None = Field(default=None)
    days_lived: int | None = Field(default=None)
    description: str | None = Field(default=None)
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
    version: int | None = Field(default=None)
    wfh_status: str | None = Field(default=None)
    working_rights: list[str] = Field(default_factory=list)


class JobDocumentCollection(BaseCollection[JobDocument]):
    collection_name = "active_jobs"
    model = JobDocument


job_col: Final[JobDocumentCollection] = JobDocumentCollection()
