from src.backend.mongo.collections.col_jobs import JobDocument


def test_null_list_fields_coerced_to_empty():
    """Explicit null in MongoDB documents should not raise a ValidationError."""
    doc = JobDocument.model_validate(
        {
            "title": "Test",
            "locations": None,
            "source_urls": None,
            "study_fields": None,
            "working_rights": None,
        }
    )
    assert doc.locations == []
    assert doc.source_urls == []
    assert doc.study_fields == []
    assert doc.working_rights == []


def test_list_fields_default_to_empty():
    doc = JobDocument(title="T")
    assert doc.locations == []
    assert doc.source_urls == []
    assert doc.study_fields == []
    assert doc.working_rights == []


def test_list_fields_preserved_when_set():
    doc = JobDocument(
        title="T", locations=["VIC", "NSW"], working_rights=["AUS_CITIZEN_PR"]
    )
    assert doc.locations == ["VIC", "NSW"]
    assert doc.working_rights == ["AUS_CITIZEN_PR"]


def test_database_name_comes_from_the_uri_path():
    """The scraper's URI carries no database path; the bot's must.

    Reusing the scraper's URI verbatim connects to an empty database and
    watches a collection that never changes, which looks exactly like a quiet
    job market rather than a misconfiguration.
    """
    from urllib.parse import urlparse

    with_db = "mongodb+srv://u:p@host.mongodb.net/default?retryWrites=true"
    without_db = "mongodb+srv://u:p@host.mongodb.net/?retryWrites=true"

    assert urlparse(with_db).path.lstrip("/") == "default"
    assert urlparse(without_db).path.lstrip("/") == ""
