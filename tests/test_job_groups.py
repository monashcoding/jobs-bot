"""Grouping the listings that are really one role.

LinkedIn advertises a role hiring in three states as three postings with three
job ids, three deadlines and three apply links. The board shows one thread with
three buttons, and these are the rules that decide what belongs together.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.backend.mongo.collections.col_jobs import Company, JobDocument
from src.backend.sql.models import JobPost
from src.core.functions.job_groups import (
    apply_label,
    apply_labels,
    group_jobs,
    live_posts,
    merge_documents,
    primary_post,
    widen_to_thread,
)

_NOW = datetime.now(tz=timezone.utc)


def _job(title: str, company: str, locations: list[str], **kwargs) -> JobDocument:
    return JobDocument(
        title=title,
        company=Company(name=company),
        locations=locations,
        **kwargs,
    )


def _post(job_id: str, minutes: int = 0, **kwargs) -> JobPost:
    return JobPost(
        job_id=job_id,
        guild_id=1,
        forum_post_id=77,
        forum_channel_id=3,
        posted_at=_NOW + timedelta(minutes=minutes),
        title="Delivery Consultant",
        company_name="AWS",
        **kwargs,
    )


# --- grouping ---------------------------------------------------------------


def test_the_aws_role_groups_into_one():
    # The real shape: one role, three states, three LinkedIn postings.
    jobs = [
        _job("Delivery Consultant", "AWS", ["QLD"]),
        _job("Delivery Consultant", "AWS", ["VIC"]),
        _job("Delivery Consultant", "AWS", ["ACT"]),
    ]

    groups = group_jobs(jobs)

    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_different_roles_at_one_company_stay_apart():
    # BCG runs both of these at once; merging them would hide a real opening.
    jobs = [
        _job("Forward Deployed AI Scientist", "BCG", ["VIC"]),
        _job("Forward Deployed AI Engineer", "BCG", ["VIC"]),
    ]

    assert len(group_jobs(jobs)) == 2


def test_the_same_title_at_different_companies_stays_apart():
    jobs = [
        _job("Data Scientist", "Quantium", ["NSW"]),
        _job("Data Scientist", "Atlassian", ["NSW"]),
    ]

    assert len(group_jobs(jobs)) == 2


def test_groups_keep_the_order_they_arrived_in():
    jobs = [
        _job("A", "X", ["NSW"]),
        _job("B", "X", ["NSW"]),
        _job("A", "X", ["VIC"]),
    ]

    groups = group_jobs(jobs)

    assert [g[0].title for g in groups] == ["A", "B"]
    assert len(groups[0]) == 2


# --- merging ----------------------------------------------------------------


def test_merging_unions_the_cities():
    jobs = [
        _job("T", "C", ["QLD"], working_rights=["AUS_CITIZEN_PR"]),
        _job("T", "C", ["VIC"], working_rights=["INTERNATIONAL"]),
        _job("T", "C", ["ACT"]),
    ]

    merged = merge_documents(jobs)

    assert merged.locations == ["QLD", "VIC", "ACT"]
    assert merged.working_rights == ["AUS_CITIZEN_PR", "INTERNATIONAL"]


def test_merging_leaves_the_primary_alone():
    jobs = [_job("T", "C", ["QLD"]), _job("T", "C", ["VIC"])]

    merge_documents(jobs)

    assert jobs[0].locations == ["QLD"], "the primary document must not be mutated"


def test_merging_a_single_listing_returns_it_unchanged():
    job = _job("T", "C", ["QLD"])

    assert merge_documents([job]) is job


def test_merging_nothing_is_an_error():
    with pytest.raises(ValueError, match="at least one"):
        merge_documents([])


def test_widening_uses_what_the_thread_knows():
    job = _job("T", "C", ["QLD"])
    job.id = "job-1"
    siblings = [
        _post("job-1", locations=["QLD"]),
        _post("job-2", locations=["VIC"], working_rights=["INTERNATIONAL"]),
    ]

    widened = widen_to_thread(job, siblings)

    assert widened.locations == ["QLD", "VIC"]
    assert widened.working_rights == ["INTERNATIONAL"]


def test_widening_a_lone_listing_changes_nothing():
    job = _job("T", "C", ["QLD"])
    job.id = "job-1"

    assert widen_to_thread(job, [_post("job-1")]) is job


# --- button labels ----------------------------------------------------------


@pytest.mark.parametrize(
    ("locations", "expected"),
    [
        (["VIC"], "Apply — VIC"),
        (["nsw"], "Apply — NSW"),
        (["AUSTRALIA"], "Apply — Australia"),
        (["VIC", "NSW"], "Apply — VIC / NSW"),
        ([], "Apply Now"),
    ],
)
def test_apply_label(locations, expected):
    assert apply_label(locations) == expected


def test_repeated_cities_are_numbered():
    # An employer posting the same city twice would otherwise give a reader two
    # identical buttons and no way to tell them apart.
    labels = apply_labels([["NSW"], ["VIC"], ["NSW"]])

    assert labels == ["Apply — NSW (1)", "Apply — VIC", "Apply — NSW (2)"]


# --- posts ------------------------------------------------------------------


def test_the_primary_is_the_oldest_post():
    posts = [_post("b", minutes=5), _post("a", minutes=0), _post("c", minutes=9)]

    assert primary_post(posts).job_id == "a"


def test_the_primary_is_stable_when_posted_together():
    # Same batch, same timestamp: the id decides, so every caller agrees.
    posts = [_post("c"), _post("a"), _post("b")]

    assert primary_post(posts).job_id == "a"


def test_live_posts_keeps_only_what_can_be_applied_to():
    posts = [
        _post("open", close_date=_NOW + timedelta(days=5)),
        _post("closed", close_date=_NOW - timedelta(days=5)),
        _post("rolling"),
        _post("outdated", outdated=True),
    ]

    assert [p.job_id for p in live_posts(posts)] == ["open", "rolling"]
