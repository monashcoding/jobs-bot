from datetime import datetime

from sqlalchemy import BigInteger
from sqlmodel import Field, SQLModel


class ExampleRecord(SQLModel, table=True):
    __tablename__ = "example_records"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(sa_type=BigInteger)
    value: str = Field(default="")


class GuildConfig(SQLModel, table=True):
    __tablename__ = "guild_configs"

    guild_id: int = Field(primary_key=True, sa_type=BigInteger)
    forum_channel_id: int = Field(sa_type=BigInteger)
    team_role_id: int | None = Field(default=None, sa_type=BigInteger)


class JobPost(SQLModel, table=True):
    __tablename__ = "job_posts"

    job_id: str = Field(primary_key=True, max_length=24)  # MongoDB ObjectId
    guild_id: int = Field(primary_key=True, sa_type=BigInteger)
    forum_post_id: int = Field(sa_type=BigInteger)         # Thread ID
    forum_channel_id: int = Field(sa_type=BigInteger)      # Parent forum channel ID
    posted_at: datetime
    awaiting_deletion: bool = Field(default=False)
    deletion_message_id: int | None = Field(default=None, sa_type=BigInteger)
