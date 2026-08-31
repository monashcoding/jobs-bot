from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.backend.mongo.collections.col_jobs import JobDocument
from src.core.functions.job_tags import apply_tag_limit, select_tags


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
    tags = select_tags(job, _tag_map("Open", "Professional"))
    assert any(t.name == "Professional" for t in tags)


def test_select_professional_tag_other():
    job = JobDocument(title="T", type="OTHER")
    tags = select_tags(job, _tag_map("Open", "Professional"))
    assert any(t.name == "Professional" for t in tags)


def test_select_professional_tag_contract():
    job = JobDocument(title="T", type="CONTRACT")
    tags = select_tags(job, _tag_map("Open", "Professional"))
    assert any(t.name == "Professional" for t in tags)


def test_select_melbourne_location():
    job = JobDocument(title="T", locations=["VIC"])
    tags = select_tags(job, _tag_map("Open", "Melbourne", "Other"))
    names = [t.name for t in tags]
    assert "Melbourne" in names
    assert "Other" not in names


def test_select_other_location_for_unknown():
    job = JobDocument(title="T", locations=["QLD"])
    tags = select_tags(job, _tag_map("Open", "Other"))
    assert any(t.name == "Other" for t in tags)


def test_select_working_rights_au():
    job = JobDocument(title="T", working_rights=["AUS_CITIZEN_PR"])
    tags = select_tags(job, _tag_map("Open", "AU Citizen/PR"))
    assert any(t.name == "AU Citizen/PR" for t in tags)


def test_select_working_rights_international():
    job = JobDocument(title="T", working_rights=["INTERNATIONAL"])
    tags = select_tags(job, _tag_map("Open", "International"))
    assert any(t.name == "International" for t in tags)


def test_select_year_tag():
    job = JobDocument(title="T", close_date=datetime(2025, 6, 1, tzinfo=timezone.utc))
    tags = select_tags(job, _tag_map("Open", "2025"))
    assert any(t.name == "2025" for t in tags)


def test_max_five_tags():
    job = JobDocument(
        title="T",
        type="INTERN",
        locations=["VIC", "NSW", "QLD"],
        working_rights=["AUS_CITIZEN_PR", "INTERNATIONAL"],
    )
    tag_map = _tag_map(
        "Open",
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
    tags = select_tags(job, _tag_map("Open", "Melbourne"))
    names = [t.name for t in tags]
    assert names.count("Melbourne") == 1


def test_missing_tag_silently_skipped():
    job = JobDocument(title="T", type="GRADUATE")
    # tag_map doesn't contain "Graduate"
    tags = select_tags(job, _tag_map("Open", "Other"))
    assert not any(t.name == "Graduate" for t in tags)


def test_select_returns_empty_without_open_tag():
    job = JobDocument(title="T", type="GRADUATE")
    tags = select_tags(job, _tag_map("Graduate"))
    assert tags == []


def test_apply_tag_limit_drops_lowest_weight_first():
    # 5 non-status tags; "Other Rights" (weight 5) should be dropped
    tags = [
        _tag(n)
        for n in (
            "Graduate",
            "Melbourne",
            "AU Citizen/PR",
            "International",
            "Other Rights",
        )
    ]
    status = _tag("Open")
    result = apply_tag_limit(status, tags)
    assert len(result) == 5
    assert result[0].name == "Open"
    assert not any(t.name == "Other Rights" for t in result)


def test_apply_tag_limit_keeps_highest_weight():
    tags = [
        _tag(n)
        for n in (
            "Other Rights",
            "International",
            "NZ Citizen/PR",
            "AU Citizen/PR",
            "Graduate",
        )
    ]
    status = _tag("Closed")
    result = apply_tag_limit(status, tags)
    assert result[0].name == "Closed"
    assert any(t.name == "Graduate" for t in result)
    assert not any(t.name == "Other Rights" for t in result)
