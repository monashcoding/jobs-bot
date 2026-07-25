from src.backend.sql.models import ExampleRecord
from src.backend.sql.tables import ExampleRecordDB


async def test_upsert_creates_record(example_record_db: ExampleRecordDB):
    record = ExampleRecord(user_id=1, value="hello")
    result = await example_record_db.upsert(record)
    assert result.id is not None
    assert result.value == "hello"
    assert result.user_id == 1


async def test_get_returns_record(example_record_db: ExampleRecordDB):
    record = await example_record_db.upsert(ExampleRecord(user_id=2, value="world"))
    fetched = await example_record_db.get(record.id)
    assert fetched is not None
    assert fetched.value == "world"


async def test_get_missing_returns_none(example_record_db: ExampleRecordDB):
    result = await example_record_db.get(9999)
    assert result is None


async def test_delete_existing(example_record_db: ExampleRecordDB):
    record = await example_record_db.upsert(ExampleRecord(user_id=3, value="bye"))
    deleted = await example_record_db.delete(record.id)
    assert deleted is True
    assert await example_record_db.get(record.id) is None


async def test_delete_missing_returns_false(example_record_db: ExampleRecordDB):
    result = await example_record_db.delete(9999)
    assert result is False


async def test_get_by_user_id(example_record_db: ExampleRecordDB):
    await example_record_db.upsert(ExampleRecord(user_id=10, value="a"))
    await example_record_db.upsert(ExampleRecord(user_id=10, value="b"))
    await example_record_db.upsert(ExampleRecord(user_id=11, value="c"))

    records = await example_record_db.get_by_user_id(10)
    assert len(records) == 2
    assert all(r.user_id == 10 for r in records)
