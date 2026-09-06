from datetime import datetime, timezone
from unittest.mock import MagicMock

from src.backend.mongo.collections.col_jobs import JobDocument
from src.core.functions.job_tags import apply_tag_limit, resync_tags, select_tags


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


def test_other_earns_no_type_tag():
    # OTHER means "not a student or graduate role", and the board is for
    # students: the scraper's board gate does not admit it, so no such listing
    # reaches a thread. Two tests here used to assert a Professional tag for
    # FULL_TIME and CONTRACT, which are not values the scraper's JobType enum
    # can hold; they passed because the tag map was written to accept them, not
    # because a listing ever arrived that way.
    job = JobDocument(title="T", type="OTHER")
    tags = select_tags(job, _tag_map("Open", "Graduate", "Intern/Student"))
    assert [t.name for t in tags] == ["Open"]


def test_a_type_outside_the_enum_earns_no_type_tag():
    job = JobDocument(title="T", type="FULL_TIME")
    tags = select_tags(job, _tag_map("Open", "Graduate"))
    assert [t.name for t in tags] == ["Open"]


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


def test_citizens_and_internationals_collapse_to_one_tag():
    # A listing that accepts both is not restricted at all, so the four rights
    # say one thing between them and are replaced by the tag that says it.
    job = JobDocument(
        title="T",
        working_rights=[
            "AUS_CITIZEN_PR",
            "NZ_CITIZEN_PR",
            "INTERNATIONAL",
            "OTHER_RIGHTS",
        ],
    )
    tag_map = _tag_map(
        "Open",
        "AU Citizen/PR",
        "NZ Citizen/PR",
        "International",
        "Anyone Can Apply",
        "Other Rights",
    )
    names = [t.name for t in select_tags(job, tag_map)]
    assert names == ["Open", "Anyone Can Apply"]


def test_international_without_citizens_keeps_its_own_tag():
    # Not the same claim: this one is open to internationals but says nothing
    # about citizens, so collapsing it to "Anyone Can Apply" would be a lie.
    job = JobDocument(title="T", working_rights=["INTERNATIONAL"])
    tag_map = _tag_map("Open", "International", "Anyone Can Apply")
    names = [t.name for t in select_tags(job, tag_map)]
    assert names == ["Open", "International"]


def test_rights_survive_a_fully_tagged_job():
    # The real shape that produced zero International tags on the board: a
    # graduate role in one city, with a year tag and every working right.
    job = JobDocument(
        title="T",
        type="GRADUATE",
        locations=["NSW"],
        close_date=datetime(2026, 10, 19, tzinfo=timezone.utc),
        working_rights=[
            "AUS_CITIZEN_PR",
            "NZ_CITIZEN_PR",
            "INTERNATIONAL",
            "OTHER_RIGHTS",
        ],
    )
    tag_map = _tag_map(
        "Open",
        "Graduate",
        "Sydney",
        "2026",
        "AU Citizen/PR",
        "NZ Citizen/PR",
        "International",
        "Anyone Can Apply",
        "Other Rights",
    )
    names = [t.name for t in select_tags(job, tag_map)]
    assert "Anyone Can Apply" in names


def test_restricted_job_keeps_its_specific_rights():
    job = JobDocument(title="T", working_rights=["AUS_CITIZEN_PR", "NZ_CITIZEN_PR"])
    tag_map = _tag_map(
        "Open", "AU Citizen/PR", "NZ Citizen/PR", "International", "Anyone Can Apply"
    )
    names = [t.name for t in select_tags(job, tag_map)]
    assert "AU Citizen/PR" in names
    assert "NZ Citizen/PR" in names
    assert "Anyone Can Apply" not in names


def test_rights_survive_a_multi_city_role():
    job = JobDocument(
        title="T",
        type="GRADUATE",
        locations=["VIC", "NSW"],
        close_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        working_rights=["INTERNATIONAL"],
    )
    tag_map = _tag_map("Open", "Graduate", "Melbourne", "Sydney", "International")
    names = [t.name for t in select_tags(job, tag_map)]
    assert "International" in names


def test_rights_survive_a_role_spread_across_many_states():
    # The real shape this was found in: EY and CommBank programs hiring across
    # five states. Melbourne and Sydney are named, everywhere else collapses to
    # "Other", and with four slots for five candidates the rights tags used to
    # be the ones dropped -- so the thread said "also somewhere else" instead of
    # saying who could apply.
    job = JobDocument(
        title="T",
        type="GRADUATE",
        locations=["ACT", "NSW", "QLD", "VIC", "WA"],
        working_rights=["AUS_CITIZEN_PR", "NZ_CITIZEN_PR"],
    )
    tag_map = _tag_map(
        "Open", "Graduate", "Melbourne", "Sydney", "Other", "AU Citizen/PR", "NZ Citizen/PR"
    )
    names = [t.name for t in select_tags(job, tag_map)]
    assert "AU Citizen/PR" in names
    assert "Other" not in names


def test_a_named_city_still_outranks_working_rights():
    # The reordering demotes only the location tag that names no location.
    # Melbourne and Sydney are what most readers filter on and still come first.
    job = JobDocument(
        title="T",
        type="GRADUATE",
        locations=["VIC", "NSW"],
        working_rights=["AUS_CITIZEN_PR", "NZ_CITIZEN_PR"],
    )
    tag_map = _tag_map(
        "Open", "Graduate", "Melbourne", "Sydney", "AU Citizen/PR", "NZ Citizen/PR"
    )
    names = [t.name for t in select_tags(job, tag_map)]
    assert names == ["Open", "Graduate", "Melbourne", "Sydney", "AU Citizen/PR"]


def test_no_year_tag_is_applied():
    # The thread name already carries the year, and a year tag permanently
    # consumes one of the forum's 20 available tags for every year that passes.
    job = JobDocument(title="T", close_date=datetime(2025, 6, 1, tzinfo=timezone.utc))
    tags = select_tags(job, _tag_map("Open", "2025"))
    assert not any(t.name == "2025" for t in tags)


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


def test_apply_tag_limit_drops_unrecognised_tags_first():
    # A tag this bot does not apply -- a leftover year tag, or one added by
    # hand -- is worth less than anything it does apply.
    tags = [_tag(n) for n in ("Graduate", "Sydney", "2026", "International")]
    result = apply_tag_limit(_tag("Open"), tags + [_tag("AU Citizen/PR")])
    names = [t.name for t in result]
    assert "International" in names
    assert "2026" not in names


# --- resync_tags -----------------------------------------------------------


def _international_job() -> JobDocument:
    return JobDocument(
        title="T",
        type="GRADUATE",
        locations=["NSW"],
        close_date=datetime(2026, 10, 19, tzinfo=timezone.utc),
        working_rights=["AUS_CITIZEN_PR", "NZ_CITIZEN_PR", "INTERNATIONAL"],
    )


_FULL_MAP = (
    "Open",
    "Closed",
    "Graduate",
    "Melbourne",
    "Sydney",
    "2026",
    "AU Citizen/PR",
    "NZ Citizen/PR",
    "International",
    "Anyone Can Apply",
    "Other Rights",
)


def test_resync_returns_none_when_tags_are_already_correct():
    job = _international_job()
    tag_map = _tag_map(*_FULL_MAP)
    current = select_tags(job, tag_map)
    assert resync_tags(job, tag_map, current) is None


def test_resync_fixes_a_thread_tagged_under_the_old_scheme():
    # What the board actually looks like today: International was trimmed at
    # post time, so the thread carries AU Citizen/PR instead.
    job = _international_job()
    tag_map = _tag_map(*_FULL_MAP)
    current = [_tag(n) for n in ("Open", "Graduate", "Sydney", "2026", "AU Citizen/PR")]
    result = resync_tags(job, tag_map, current)
    assert result is not None
    names = [t.name for t in result]
    assert names[0] == "Open"
    assert "Anyone Can Apply" in names


def test_resync_strips_a_leftover_year_tag():
    # Threads posted before year tags were retired still carry one.
    job = _international_job()
    tag_map = _tag_map(*_FULL_MAP)
    current = [_tag(n) for n in ("Open", "Graduate", "Sydney", "2026")]
    result = resync_tags(job, tag_map, current)
    assert result is not None
    assert "2026" not in [t.name for t in result]


def test_resync_picks_up_a_location_the_scraper_added_later():
    job = JobDocument(title="T", type="GRADUATE", locations=["NSW", "VIC"])
    tag_map = _tag_map(*_FULL_MAP)
    current = [_tag(n) for n in ("Open", "Graduate", "Sydney")]
    result = resync_tags(job, tag_map, current)
    assert result is not None
    assert "Melbourne" in [t.name for t in result]


def test_resync_does_not_reopen_a_closed_thread():
    job = _international_job()
    tag_map = _tag_map(*_FULL_MAP)
    current = [_tag(n) for n in ("Closed", "Graduate", "Sydney", "2026")]
    result = resync_tags(job, tag_map, current)
    assert result is not None
    names = [t.name for t in result]
    assert names[0] == "Closed"
    assert "Open" not in names


def test_resync_defaults_a_statusless_thread_to_open():
    job = _international_job()
    tag_map = _tag_map(*_FULL_MAP)
    result = resync_tags(job, tag_map, [_tag("Graduate")])
    assert result is not None
    assert result[0].name == "Open"


def test_resync_gives_up_when_the_channel_has_no_open_tag():
    job = _international_job()
    tag_map = _tag_map("Graduate", "Sydney")
    assert resync_tags(job, tag_map, [_tag("Graduate")]) is None
