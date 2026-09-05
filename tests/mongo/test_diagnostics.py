"""The diagnose numbers are what someone acts on, so they get tested.

"The filter is broken", "the filter works and the scraper marks everything
eligible" and "the bot is reading the wrong database" look identical from
inside Discord and need different fixes. If these counts are wrong they point
at the wrong one.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from src.core.functions.job_diagnostics import collect_board_diagnostics

NOW = datetime.now(tz=timezone.utc)


def _docs() -> list[dict]:
    return [
        # Postable: eligible, open.
        {"_id": "p1", "board_eligible": True, "company": {"name": "Atlassian"}},
        {
            "_id": "p2",
            "board_eligible": True,
            "close_date": NOW + timedelta(days=10),
            "company": {"name": "Atlassian"},
        },
        {
            "_id": "p3",
            "board_eligible": True,
            "close_date": None,
            "company": {"name": "Canva"},
        },
        # Eligible but past its deadline.
        {
            "_id": "closed",
            "board_eligible": True,
            "close_date": NOW - timedelta(days=2),
            "company": {"name": "Canva"},
        },
        # Eligible but withdrawn.
        {"_id": "old", "board_eligible": True, "outdated": True},
        # Scored and rejected.
        {"_id": "no", "board_eligible": False},
        # Never scored.
        {"_id": "unscored"},
    ]


async def _collect(job_col, guild_id=1, existing_records=()):
    await job_col._col().insert_many(_docs())
    with (
        patch("src.core.functions.job_diagnostics.job_col", job_col),
        patch(
            "src.core.functions.job_diagnostics.job_post_db.get_by_guild",
            new=AsyncMock(return_value=list(existing_records)),
        ),
    ):
        return await collect_board_diagnostics(guild_id)


async def test_eligibility_counts_split_rejected_from_never_scored(job_col):
    diag = await _collect(job_col)

    assert diag.total == 7
    assert diag.eligible == 5
    assert diag.ineligible == 1
    # The distinction that matters: never scored is the scraper not having run,
    # not the scraper saying no.
    assert diag.unscored == 1


async def test_open_closed_and_outdated_are_separated(job_col):
    diag = await _collect(job_col)

    # No deadline counts as open: rolling applications are common.
    assert diag.eligible_open == 3
    assert diag.eligible_closed == 1
    assert diag.eligible_outdated == 1


async def test_would_post_excludes_jobs_that_already_have_threads(job_col):
    from unittest.mock import MagicMock

    existing = [MagicMock(job_id="p1", guild_id=1)]
    diag = await _collect(job_col, existing_records=existing)

    assert diag.records_this_guild == 1
    # Three postable, one already posted.
    assert diag.would_post == 2


async def test_company_breakdown_counts_only_postable_jobs(job_col):
    diag = await _collect(job_col)

    counts = dict(diag.top_companies)
    assert counts.get("Atlassian") == 2
    # Canva has two documents but only one is postable; the closed one is not
    # counted, or the breakdown would blame the wrong employer.
    assert counts.get("Canva") == 1


async def test_database_name_is_reported(job_col):
    # The classic misconfiguration is the bot reading an empty database called
    # "bot" because MONGODB_URI carried no path, which looks like a quiet market.
    diag = await _collect(job_col)

    assert diag.database == "test_db"
