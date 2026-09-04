"""Closing a job post is not the end of its thread.

Applications closing is when the interesting conversation often starts: people
come back to say they got an interview, or an offer. Archiving hides the post
from the forum view, which ends that conversation before it happens. So a post
is archived on close only when nobody is talking in it.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from src.backend.sql.models import DeadlineReminder, JobPost
from src.cogs.workers.deadline_watcher import DeadlineWatcher

BOT_USER = MagicMock(name="bot_user")


def _post() -> JobPost:
    return JobPost(
        job_id="abc",
        guild_id=1,
        forum_post_id=2,
        forum_channel_id=3,
        posted_at=datetime.now(tz=timezone.utc),
        title="Grad Software Engineer",
        company_name="Atlassian",
        close_date=datetime.now(tz=timezone.utc) - timedelta(hours=1),
    )


def _thread(history_messages: list) -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.id = 2
    thread.applied_tags = []
    thread.parent = None
    thread.parent_id = 3
    thread.edit = AsyncMock()
    thread.send = AsyncMock()

    def history(**kwargs):
        async def gen():
            for message in history_messages:
                yield message

        return gen()

    thread.history = history
    return thread


def _watcher() -> DeadlineWatcher:
    bot = MagicMock()
    bot.user = BOT_USER
    with patch.object(DeadlineWatcher, "check_deadlines", MagicMock()):
        watcher = DeadlineWatcher(bot)
    return watcher


def _message(author) -> MagicMock:
    message = MagicMock()
    message.author = author
    return message


def _archived_calls(thread: MagicMock) -> list:
    return [c for c in thread.edit.await_args_list if c.kwargs.get("archived") is True]


async def test_quiet_post_is_archived_on_close():
    # Only the bot has spoken: its own reminders and closing notice are not a
    # conversation, so there is nothing to keep the post open for.
    thread = _thread([_message(BOT_USER), _message(BOT_USER)])
    watcher = _watcher()

    with patch(
        "src.cogs.workers.deadline_watcher.job_post_db.mark_reminder_sent",
        new=AsyncMock(),
    ):
        await watcher._on_closed(thread, _post())

    assert _archived_calls(thread), "a post nobody is using should be archived"


async def test_post_with_live_discussion_is_not_archived_on_close():
    thread = _thread([_message(BOT_USER), _message(MagicMock(name="applicant"))])
    watcher = _watcher()

    with patch(
        "src.cogs.workers.deadline_watcher.job_post_db.mark_reminder_sent",
        new=AsyncMock(),
    ):
        await watcher._on_closed(thread, _post())

    assert not _archived_calls(thread), (
        "someone discussing their interview should not have the thread archived "
        "out from under them"
    )


async def test_closing_still_renames_tags_and_notifies_either_way():
    # Leaving the thread open must not skip the rest of the closing treatment.
    thread = _thread([_message(MagicMock(name="applicant"))])
    watcher = _watcher()

    mark = AsyncMock()
    with patch(
        "src.cogs.workers.deadline_watcher.job_post_db.mark_reminder_sent", new=mark
    ):
        await watcher._on_closed(thread, _post())

    renamed = [c for c in thread.edit.await_args_list if "name" in c.kwargs]
    assert renamed and renamed[0].kwargs["name"].startswith("❌ ")
    thread.send.assert_awaited_once()
    assert mark.await_args.args[2] is DeadlineReminder.CLOSED


async def test_unreadable_history_leaves_the_thread_open():
    # Archiving a thread somebody is talking in cannot be undone by waiting,
    # whereas an unarchived dead thread is collected by Discord's own timer.
    thread = _thread([])

    def boom(**kwargs):
        raise RuntimeError("history unavailable")

    thread.history = boom
    watcher = _watcher()

    with patch(
        "src.cogs.workers.deadline_watcher.job_post_db.mark_reminder_sent",
        new=AsyncMock(),
    ):
        await watcher._on_closed(thread, _post())

    assert not _archived_calls(thread)


async def test_history_is_bounded_to_the_quiet_window():
    from src.config import CLOSE_ARCHIVE_QUIET_DAYS

    captured: dict = {}
    thread = _thread([])

    def history(**kwargs):
        captured.update(kwargs)

        async def gen():
            return
            yield

        return gen()

    thread.history = history
    watcher = _watcher()

    with patch(
        "src.cogs.workers.deadline_watcher.job_post_db.mark_reminder_sent",
        new=AsyncMock(),
    ):
        await watcher._on_closed(thread, _post())

    # Bounded, so closing a long-running post does not walk its whole history.
    age = datetime.now(tz=timezone.utc) - captured["after"]
    assert abs(age - timedelta(days=CLOSE_ARCHIVE_QUIET_DAYS)) < timedelta(minutes=1)
