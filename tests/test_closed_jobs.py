"""A closed role must not get a thread.

Posting one is noise twice over: the thread is created, and then the deadline
watcher renames it, tags it Closed and archives it on its next pass. The board
advertises dead listings and the forum churns for nothing.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.mongo.collections.col_jobs import JobDocument
from src.core.functions.job_eligibility import is_open_for_applications

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def _job(**kwargs) -> JobDocument:
    return JobDocument(title="Grad SWE", board_eligible=True, **kwargs)


def test_deadline_in_the_past_is_closed():
    assert not is_open_for_applications(_job(close_date=NOW - timedelta(days=1)), NOW)


def test_deadline_in_the_future_is_open():
    assert is_open_for_applications(_job(close_date=NOW + timedelta(days=1)), NOW)


def test_deadline_exactly_now_is_closed():
    # The boundary belongs to closed: a deadline of "now" has passed.
    assert not is_open_for_applications(_job(close_date=NOW), NOW)


def test_no_deadline_is_open():
    # Default-allow, unlike board_eligible. Plenty of real listings carry no
    # deadline and rolling applications are common; refusing them would empty
    # the board of applicable roles.
    assert is_open_for_applications(_job(), NOW)


def test_outdated_is_closed_even_with_a_future_deadline():
    job = _job(close_date=NOW + timedelta(days=30), outdated=True)
    assert not is_open_for_applications(job, NOW)


def test_naive_close_date_does_not_raise():
    # Documents are read tz_aware, but one malformed date must not take down
    # the watcher; it is read as UTC.
    naive_past = datetime(2026, 9, 4, 12, 0)  # noqa: DTZ001 - naive on purpose
    assert not is_open_for_applications(_job(close_date=naive_past), NOW)


@pytest.mark.parametrize(
    ("eligible", "close_offset_days", "should_post"),
    [
        (True, 30, True),  # the only combination that posts
        (True, -1, False),  # eligible but closed
        (False, 30, False),  # open but not board material
        (False, -1, False),
    ],
)
async def test_post_job_to_guild_requires_both_eligible_and_open(
    eligible, close_offset_days, should_post
):
    from src.core.functions import job_post

    job = JobDocument(
        title="Grad SWE",
        board_eligible=eligible,
        close_date=datetime.now(tz=timezone.utc) + timedelta(days=close_offset_days),
    )
    job.id = "abc"

    created = False

    async def fake_create_thread(**kwargs):
        nonlocal created
        created = True
        return MagicMock(id=5), MagicMock(id=6)

    import discord

    channel = MagicMock(spec=discord.ForumChannel)
    channel.create_thread = fake_create_thread
    channel.id = 3
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=channel)

    config = MagicMock(guild_id=1, forum_channel_id=3)

    with (
        patch.object(job_post, "ensure_tags", new=AsyncMock(return_value={})),
        patch.object(job_post, "select_tags", MagicMock(return_value=[])),
        patch.object(job_post.job_post_db, "upsert", new=AsyncMock()),
    ):
        result = await job_post.post_job_to_guild(bot, job, config)

    assert result is should_post
    assert created is should_post
