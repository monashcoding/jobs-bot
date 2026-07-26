from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, BigInteger, Column, DateTime, Text
from sqlmodel import Field, SQLModel


class DeadlineReminder(StrEnum):
    """Reminder stages tracked per job post to avoid re-sending."""

    REMINDER_2W = "2w"
    REMINDER_1W = "1w"
    REMINDER_3D = "3d"
    REMINDER_1D = "1d"
    CLOSED = "closed"


class GuildConfig(SQLModel, table=True):
    __tablename__ = "job_guild_configs"

    guild_id: int = Field(primary_key=True, sa_type=BigInteger)
    forum_channel_id: int = Field(sa_type=BigInteger)
    team_role_id: int | None = Field(default=None, sa_type=BigInteger)

    # Notification roles pinged when a new post of each type is created
    intern_role_id: int | None = Field(default=None, sa_type=BigInteger)
    grad_role_id: int | None = Field(default=None, sa_type=BigInteger)
    junior_role_id: int | None = Field(default=None, sa_type=BigInteger)
    experienced_role_id: int | None = Field(default=None, sa_type=BigInteger)


class JobPost(SQLModel, table=True):
    __tablename__ = "job_posts"

    # Identity
    job_id: str = Field(primary_key=True, max_length=24)  # MongoDB ObjectId
    guild_id: int = Field(primary_key=True, sa_type=BigInteger)

    # Forum post metadata
    forum_post_id: int = Field(sa_type=BigInteger)  # Thread ID
    forum_channel_id: int = Field(sa_type=BigInteger)  # Parent forum channel ID
    posted_at: datetime = Field(sa_type=DateTime(timezone=True))
    awaiting_deletion: bool = Field(default=False)
    deletion_message_id: int | None = Field(default=None, sa_type=BigInteger)

    # Job data (denormalized from MongoDB)
    title: str
    job_type: str | None = Field(default=None)
    application_url: str | None = Field(default=None)
    one_liner: str | None = Field(default=None)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    close_date: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
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
    job_created_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )
    job_updated_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True)
    )

    # Deadline reminder tracking: list of DeadlineReminder values already sent.
    deadline_reminders_sent: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
