"""A job leaving Mongo does not mean the role is over.

The watcher deleted the thread for any removed job nobody had posted in, so a
source dropping a live listing -- a moved page, a hiccuping feed, a churning
re-scrape -- took a still-open opportunity off the board with it.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.sql.models import JobPost
from src.cogs.workers.job_watcher import JobWatcher, still_open


def _post(**kwargs) -> JobPost:
    return JobPost(
        job_id="job-1",
        guild_id=1,
        forum_post_id=99,
        forum_channel_id=3,
        posted_at=datetime.now(tz=timezone.utc),
        title="Grad Software Engineer",
        **kwargs,
    )


_FUTURE = datetime.now(tz=timezone.utc) + timedelta(days=30)
_PAST = datetime.now(tz=timezone.utc) - timedelta(days=30)


@pytest.mark.parametrize(
    ("post", "expected"),
    [
        (_post(close_date=_FUTURE), True),
        (_post(close_date=_PAST), False),
        # No deadline at all: rolling applications are common, and an absent
        # date says nothing about whether the role is over.
        (_post(close_date=None), True),
        # Already known to be over, whatever its date says.
        (_post(close_date=_FUTURE, outdated=True), False),
    ],
)
def test_still_open(post, expected):
    assert still_open(post) is expected


def test_still_open_tolerates_a_naive_close_date():
    naive = datetime.now() + timedelta(days=30)  # noqa: DTZ005
    assert still_open(_post(close_date=naive)) is True


async def _handle_delete(post: JobPost) -> MagicMock:
    thread = MagicMock()
    thread.delete = AsyncMock()
    thread.send = AsyncMock(return_value=MagicMock(id=5))
    thread.history = MagicMock(return_value=_empty())

    watcher = JobWatcher(MagicMock())
    watcher.bot.fetch_channel = AsyncMock(return_value=thread)

    with (
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_job_id",
            new=AsyncMock(return_value=[post]),
        ),
        patch(
            "src.cogs.workers.job_watcher.job_post_db.delete", new=AsyncMock()
        ) as delete_record,
        patch(
            "src.cogs.workers.job_watcher.job_post_db.set_awaiting_deletion",
            new=AsyncMock(),
        ) as awaiting,
    ):
        await watcher._handle_delete("job-1")

    thread.delete_record = delete_record
    thread.awaiting = awaiting
    return thread


async def _empty():
    return
    yield  # pragma: no cover


async def test_an_open_role_is_kept_untouched():
    thread = await _handle_delete(_post(close_date=_FUTURE))

    thread.delete.assert_not_awaited()
    # Not even a prompt: there is nothing to decide while people can still apply.
    thread.send.assert_not_awaited()
    thread.delete_record.assert_not_awaited()
    thread.awaiting.assert_not_awaited()


async def test_a_closed_bot_only_thread_is_still_deleted():
    thread = await _handle_delete(_post(close_date=_PAST))

    thread.delete.assert_awaited_once()
    thread.delete_record.assert_awaited_once()


async def test_a_closed_thread_with_people_in_it_still_prompts():
    async def history(**kwargs):
        yield MagicMock(author=MagicMock())

    post = _post(close_date=_PAST)
    thread = MagicMock()
    thread.delete = AsyncMock()
    thread.send = AsyncMock(return_value=MagicMock(id=5))
    thread.history = history

    watcher = JobWatcher(MagicMock())
    watcher.bot.fetch_channel = AsyncMock(return_value=thread)

    with (
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_job_id",
            new=AsyncMock(return_value=[post]),
        ),
        patch(
            "src.cogs.workers.job_watcher.job_post_db.set_awaiting_deletion",
            new=AsyncMock(),
        ) as awaiting,
    ):
        await watcher._handle_delete("job-1")

    thread.delete.assert_not_awaited()
    thread.send.assert_awaited_once()
    awaiting.assert_awaited_once()
