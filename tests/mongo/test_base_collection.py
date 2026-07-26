import pytest

from src.backend.mongo.collections.col_jobs import JobDocument, JobDocumentCollection


async def test_upsert_creates_document(job_col: JobDocumentCollection) -> None:
    doc = JobDocument(title="Software Engineer", type="GRADUATE")
    result = await job_col.upsert(doc)
    assert result.id is not None
    assert result.title == "Software Engineer"
    assert result.type == "GRADUATE"


async def test_get_returns_document(job_col: JobDocumentCollection) -> None:
    inserted = await job_col.upsert(JobDocument(title="Data Analyst"))
    fetched = await job_col.get(inserted.id)
    assert fetched is not None
    assert fetched.title == "Data Analyst"


async def test_get_missing_returns_none(job_col: JobDocumentCollection) -> None:
    result = await job_col.get("507f1f77bcf86cd799439011")
    assert result is None


async def test_delete_existing(job_col: JobDocumentCollection) -> None:
    doc = await job_col.upsert(JobDocument(title="To Delete"))
    deleted = await job_col.delete(doc.id)
    assert deleted is True
    assert await job_col.get(doc.id) is None


async def test_delete_missing_returns_false(job_col: JobDocumentCollection) -> None:
    result = await job_col.delete("507f1f77bcf86cd799439011")
    assert result is False


async def test_find_by_filter(job_col: JobDocumentCollection) -> None:
    await job_col.upsert(JobDocument(title="Intern A", type="INTERNSHIP"))
    await job_col.upsert(JobDocument(title="Intern B", type="INTERNSHIP"))
    await job_col.upsert(JobDocument(title="Grad Role", type="GRADUATE"))

    docs = await job_col.find({"type": "INTERNSHIP"})
    assert len(docs) == 2
    assert all(d.type == "INTERNSHIP" for d in docs)


@pytest.mark.skip(
    reason="mongomock-motor does not support change streams; requires a real replica set"
)
async def test_watch_change_stream(job_col: JobDocumentCollection) -> None:
    async with job_col.watch() as stream:
        await job_col.upsert(JobDocument(title="New Job"))
        event = await stream.next()
        assert event["operationType"] == "insert"
