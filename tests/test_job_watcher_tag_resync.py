"""Tag drift is corrected on update, without the board noticing.

Threads are tagged once at post time and the scraper keeps revising the document
behind them, so tags go stale. The correction has to land silently: it must not
unarchive a dead thread, must not reopen a closed one, and must not spend an
edit on a thread whose tags are already right.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.backend.mongo.collections.col_jobs import JobDocument
from src.cogs.workers.job_watcher import JobWatcher


def _tag(name: str):
    t = MagicMock(spec=discord.ForumTag)
    t.name = name
    return t


def _forum(*tag_names: str) -> MagicMock:
    forum = MagicMock(spec=discord.ForumChannel)
    forum.id = 1
    forum.available_tags = [_tag(n) for n in tag_names]
    forum.create_tag = AsyncMock(side_effect=lambda name, **kw: _tag(name))
    return forum


def _thread(forum: MagicMock, *applied: str, archived: bool = False) -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.id = 2
    thread.parent = forum
    thread.parent_id = forum.id
    thread.archived = archived
    thread.applied_tags = [_tag(n) for n in applied]
    thread.edit = AsyncMock()
    return thread


_ALL_TAGS = (
    "Open",
    "Closed",
    "Graduate",
    "Sydney",
    "Melbourne",
    "Other",
    "AU Citizen/PR",
    "NZ Citizen/PR",
    "International",
    "Anyone Can Apply",
    "Other Rights",
    "Intern/Student",
    "Professional",
)


@pytest.fixture
def watcher() -> JobWatcher:
    return JobWatcher(MagicMock())


def _job(**kwargs) -> JobDocument:
    return JobDocument(
        title="T",
        type="GRADUATE",
        locations=["NSW"],
        working_rights=["AUS_CITIZEN_PR", "NZ_CITIZEN_PR", "INTERNATIONAL"],
        **kwargs,
    )


async def test_stale_tags_are_corrected(watcher):
    forum = _forum(*_ALL_TAGS)
    thread = _thread(forum, "Open", "Graduate", "Sydney", "AU Citizen/PR")

    await watcher._resync_tags(thread, _job())

    thread.edit.assert_awaited_once()
    names = [t.name for t in thread.edit.await_args.kwargs["applied_tags"]]
    assert "Anyone Can Apply" in names


async def test_correct_tags_cost_no_edit(watcher):
    forum = _forum(*_ALL_TAGS)
    thread = _thread(forum, "Open", "Graduate", "Sydney", "Anyone Can Apply")

    await watcher._resync_tags(thread, _job())

    thread.edit.assert_not_awaited()


async def test_archived_threads_are_left_alone(watcher):
    # Editing an archived thread unarchives it, dragging a dead posting back to
    # the top of the forum -- the loudest thing this could do.
    forum = _forum(*_ALL_TAGS)
    thread = _thread(
        forum, "Closed", "Graduate", "Sydney", "AU Citizen/PR", archived=True
    )

    await watcher._resync_tags(thread, _job())

    thread.edit.assert_not_awaited()


async def test_a_closed_thread_is_not_reopened(watcher):
    forum = _forum(*_ALL_TAGS)
    thread = _thread(forum, "Closed", "Graduate", "Sydney", "AU Citizen/PR")

    await watcher._resync_tags(thread, _job())

    names = [t.name for t in thread.edit.await_args.kwargs["applied_tags"]]
    assert names[0] == "Closed"
    assert "Open" not in names


async def test_non_forum_parent_is_ignored(watcher):
    thread = MagicMock(spec=discord.Thread)
    thread.id = 2
    thread.archived = False
    thread.parent = MagicMock(spec=discord.TextChannel)
    thread.applied_tags = []
    thread.edit = AsyncMock()

    await watcher._resync_tags(thread, _job())

    thread.edit.assert_not_awaited()


async def test_update_resyncs_tags_on_a_live_thread(watcher):
    """The whole path: an update event reaches _resync_tags for each post."""
    forum = _forum(*_ALL_TAGS)
    thread = _thread(forum, "Open", "Graduate", "Sydney", "AU Citizen/PR")
    thread.fetch_message = AsyncMock(return_value=MagicMock(edit=AsyncMock()))
    watcher.bot.fetch_channel = AsyncMock(return_value=thread)

    post = MagicMock(job_id="job-1", guild_id=1, forum_post_id=2)
    event = MagicMock(document_id="job-1", full_document=_job())
    event.operation.value = "update"

    with (
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_job_id",
            new=AsyncMock(return_value=[post]),
        ),
        patch(
            "src.cogs.workers.job_watcher.job_post_db.sync_fields",
            new=AsyncMock(),
        ),
    ):
        await watcher._handle_update(event)

    thread.edit.assert_awaited_once()
    names = [t.name for t in thread.edit.await_args.kwargs["applied_tags"]]
    assert "Anyone Can Apply" in names
