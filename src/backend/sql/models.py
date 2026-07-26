from datetime import datetime

from sqlalchemy import JSON, BigInteger, Column, Text
from sqlmodel import Field, SQLModel


class GuildConfig(SQLModel, table=True):
    __tablename__ = "guild_configs"

    guild_id: int = Field(primary_key=True, sa_type=BigInteger)
    forum_channel_id: int = Field(sa_type=BigInteger)
    team_role_id: int | None = Field(default=None, sa_type=BigInteger)


class JobPost(SQLModel, table=True):
    __tablename__ = "job_posts"

    # Identity
    job_id: str = Field(primary_key=True, max_length=24)  # MongoDB ObjectId
    guild_id: int = Field(primary_key=True, sa_type=BigInteger)

    # Forum post metadata
    forum_post_id: int = Field(sa_type=BigInteger)  # Thread ID
    forum_channel_id: int = Field(sa_type=BigInteger)  # Parent forum channel ID
    posted_at: datetime
    awaiting_deletion: bool = Field(default=False)
    deletion_message_id: int | None = Field(default=None, sa_type=BigInteger)

    # Job data (denormalized from MongoDB)
    title: str
    job_type: str | None = Field(default=None)
    application_url: str | None = Field(default=None)
    one_liner: str | None = Field(default=None)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    close_date: datetime | None = Field(default=None)
    industry_field: str | None = Field(default=None)
    is_sponsored: bool = Field(default=False)
    outdated: bool = Field(default=False)
    source: str | None = Field(default=None)
    version: str | None = Field(default=None)
    wfh_status: str | None = Field(default=None)
    days_lived: int | None = Field(default=None)
    fingerprint: str | None = Field(default=None)
    locations: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    source_urls: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    study_fields: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    working_rights: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    company_name: str = Field(default="")
    company_website: str | None = Field(default=None)
    company_logo: str | None = Field(default=None)
    job_created_at: datetime | None = Field(default=None)
    job_updated_at: datetime | None = Field(default=None)
