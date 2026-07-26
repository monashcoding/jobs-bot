from unittest.mock import MagicMock

from src.backend.mongo.collections.col_jobs import JobDocument
from src.core.functions.job_tags import select_tags


def _tag(name: str):
    t = MagicMock()
    t.name = name
    return t


def _tag_map(*names: str) -> dict:
    return {n: _tag(n) for n in names}


def test_select_open_tag_always_first():
    job = JobDocument(title="T", type="GRADUATE")
    tags = select_tags(job, _tag_map("Open", "Graduate"))
    assert tags[0].name == "Open"


def test_select_type_tag():
    job = JobDocument(title="T", type="GRADUATE")
    tags = select_tags(job, _tag_map("Open", "Graduate"))
    assert any(t.name == "Graduate" for t in tags)


def test_select_intern_tag():
    job = JobDocument(title="T", type="INTERN")
    tags = select_tags(job, _tag_map("Open", "Intern/Student"))
    assert any(t.name == "Intern/Student" for t in tags)


def test_select_professional_tag_full_time():
    job = JobDocument(title="T", type="FULL_TIME")
    tags = select_tags(job, _tag_map("Professional"))
    assert any(t.name == "Professional" for t in tags)


def test_select_professional_tag_other():
    job = JobDocument(title="T", type="OTHER")
    tags = select_tags(job, _tag_map("Professional"))
    assert any(t.name == "Professional" for t in tags)


def test_select_professional_tag_contract():
    job = JobDocument(title="T", type="CONTRACT")
    tags = select_tags(job, _tag_map("Professional"))
    assert any(t.name == "Professional" for t in tags)


def test_select_melbourne_location():
    job = JobDocument(title="T", locations=["VIC"])
    tags = select_tags(job, _tag_map("Melbourne", "Other"))
    names = [t.name for t in tags]
    assert "Melbourne" in names
    assert "Other" not in names


def test_select_other_location_for_unknown():
    job = JobDocument(title="T", locations=["QLD"])
    tags = select_tags(job, _tag_map("Other"))
    assert any(t.name == "Other" for t in tags)


def test_select_working_rights_au():
    job = JobDocument(title="T", working_rights=["AUS_CITIZEN_PR"])
    tags = select_tags(job, _tag_map("AU Citizen/PR"))
    assert any(t.name == "AU Citizen/PR" for t in tags)


def test_select_working_rights_international():
    job = JobDocument(title="T", working_rights=["INTERNATIONAL"])
    tags = select_tags(job, _tag_map("International"))
    assert any(t.name == "International" for t in tags)


def test_select_year_tag():
    from datetime import datetime, timezone

    job = JobDocument(title="T", close_date=datetime(2025, 6, 1, tzinfo=timezone.utc))
    tags = select_tags(job, _tag_map("2025"))
    assert any(t.name == "2025" for t in tags)


def test_max_five_tags():
    job = JobDocument(
        title="T",
        type="INTERN",
        locations=["VIC", "NSW", "QLD"],
        working_rights=["AUS_CITIZEN_PR", "INTERNATIONAL"],
    )
    tag_map = _tag_map(
        "Intern/Student",
        "Melbourne",
        "Sydney",
        "Other",
        "AU Citizen/PR",
        "International",
    )
    tags = select_tags(job, tag_map)
    assert len(tags) <= 5


def test_no_duplicate_tags():
    job = JobDocument(title="T", locations=["VIC", "VIC"])
    tags = select_tags(job, _tag_map("Melbourne"))
    names = [t.name for t in tags]
    assert names.count("Melbourne") == 1


def test_missing_tag_silently_skipped():
    job = JobDocument(title="T", type="GRADUATE")
    # tag_map doesn't contain "Graduate"
    tags = select_tags(job, _tag_map("Other"))
    assert not any(t.name == "Graduate" for t in tags)
