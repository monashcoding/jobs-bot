import mongomock_motor
import pytest_asyncio

from src.backend.mongo.client import MongoDatabase
from src.backend.mongo.collections.col_example import ExampleDocumentCollection


@pytest_asyncio.fixture
async def test_mongo() -> MongoDatabase:
    """In-memory MongoDB backed by mongomock-motor (no real MongoDB needed)."""
    db = MongoDatabase()
    db._client = mongomock_motor.AsyncMongoMockClient()
    db._db = db._client["test_db"]
    return db


@pytest_asyncio.fixture
async def example_col(test_mongo: MongoDatabase) -> ExampleDocumentCollection:
    return ExampleDocumentCollection(mongo=test_mongo)
