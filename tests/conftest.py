import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from src.backend.sql.client import Database
from src.backend.sql.models import GuildConfig, JobPost  # noqa: F401 - register tables
from src.backend.sql.tables import GuildConfigDB, JobPostDB


@pytest_asyncio.fixture
async def test_db():
    """In-memory SQLite database for testing."""
    db = Database()
    db._engine = create_async_engine("sqlite+aiosqlite://", echo=True)
    db._session_factory = async_sessionmaker(
        db._engine, class_=AsyncSession, expire_on_commit=False
    )
    async with db._engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield db
    await db.close()


@pytest_asyncio.fixture
async def guild_config_db(test_db: Database) -> GuildConfigDB:
    return GuildConfigDB(db=test_db)


@pytest_asyncio.fixture
async def job_post_db(test_db: Database) -> JobPostDB:
    return JobPostDB(db=test_db)
