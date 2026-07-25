import pytest

from src.backend.mongo.collections.col_example import (
    ExampleDocument,
    ExampleDocumentCollection,
)


async def test_upsert_creates_document(example_col: ExampleDocumentCollection) -> None:
    doc = ExampleDocument(user_id=1, value="hello")
    result = await example_col.upsert(doc)
    assert result.id is not None
    assert result.user_id == 1
    assert result.value == "hello"


async def test_get_returns_document(example_col: ExampleDocumentCollection) -> None:
    inserted = await example_col.upsert(ExampleDocument(user_id=2, value="world"))
    fetched = await example_col.get(inserted.id)
    assert fetched is not None
    assert fetched.value == "world"


async def test_get_missing_returns_none(example_col: ExampleDocumentCollection) -> None:
    result = await example_col.get("507f1f77bcf86cd799439011")
    assert result is None


async def test_delete_existing(example_col: ExampleDocumentCollection) -> None:
    doc = await example_col.upsert(ExampleDocument(user_id=3, value="bye"))
    deleted = await example_col.delete(doc.id)
    assert deleted is True
    assert await example_col.get(doc.id) is None


async def test_delete_missing_returns_false(example_col: ExampleDocumentCollection) -> None:
    result = await example_col.delete("507f1f77bcf86cd799439011")
    assert result is False


async def test_find_by_user_id(example_col: ExampleDocumentCollection) -> None:
    await example_col.upsert(ExampleDocument(user_id=10, value="a"))
    await example_col.upsert(ExampleDocument(user_id=10, value="b"))
    await example_col.upsert(ExampleDocument(user_id=11, value="c"))

    docs = await example_col.find_by_user_id(10)
    assert len(docs) == 2
    assert all(d.user_id == 10 for d in docs)


@pytest.mark.skip(reason="mongomock-motor does not support change streams; requires a real replica set")
async def test_watch_change_stream(example_col: ExampleDocumentCollection) -> None:
    async with example_col.watch() as stream:
        await example_col.upsert(ExampleDocument(user_id=1, value="new"))
        event = await stream.next()
        assert event["operationType"] == "insert"
