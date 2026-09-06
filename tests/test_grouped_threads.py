"""One thread for a role, however many cities it is advertised in.

The lifecycle is where this earns its keep: the thread has to survive one city
closing, pick up a city that opens later, and only finish when the last listing
on it does.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.backend.mongo.collections.col_jobs import Company, JobDocument
from src.backend.sql.models import DeadlineReminder, JobPost
from src.cogs.workers.deadline_watcher import DeadlineWatcher
from src.cogs.workers.job_watcher import JobWatcher
from src.core.functions.job_post import ApplyTarget, build_apply_view

_NOW = datetime.now(tz=timezone.utc)


def _job(locations: list[str], job_id: str = "job-1", **kwargs) -> JobDocument:
    job = JobDocument(
        title="Delivery Consultant",
        company=Company(name="AWS"),
        locations=locations,
        board_eligible=True,
        **kwargs,
    )
    job.id = job_id
    return job


def _post(job_id: str, locations: list[str], minutes: int = 0, **kwargs) -> JobPost:
    return JobPost(
        job_id=job_id,
        guild_id=1,
        forum_post_id=77,
        forum_channel_id=3,
        posted_at=_NOW + timedelta(minutes=minutes),
        title="Delivery Consultant",
        company_name="AWS",
        locations=locations,
        **kwargs,
    )


def _thread() -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.id = 77
    thread.parent_id = 3
    thread.archived = False
    thread.applied_tags = []
    thread.edit = AsyncMock()
    thread.send = AsyncMock()
    thread.fetch_message = AsyncMock(return_value=MagicMock(edit=AsyncMock()))
    return thread


# --- the buttons ------------------------------------------------------------


def test_one_listing_keeps_the_plain_apply_button():
    view = build_apply_view([ApplyTarget(job_id="job-1", locations=["NSW"])])

    labels = [item.label for item in view.children]
    assert labels == ["Apply Now", "My Applications"]


def test_a_split_role_gets_a_button_per_city():
    view = build_apply_view(
        [
            ApplyTarget(job_id="job-1", locations=["QLD"]),
            ApplyTarget(job_id="job-2", locations=["VIC"]),
            ApplyTarget(job_id="job-3", locations=["ACT"]),
        ]
    )

    labels = [item.label for item in view.children]
    assert labels == [
        "Apply — QLD",
        "Apply — VIC",
        "Apply — ACT",
        "My Applications",
    ]
    # Each button goes to its own city's listing.
    assert "job-2" in view.children[1].url


def test_the_button_cap_is_respected():
    # Discord refuses a view with too many components, and a thread with most
    # of its links beats a thread that failed to post.
    targets = [ApplyTarget(job_id=f"job-{i}", locations=[f"L{i}"]) for i in range(40)]

    view = build_apply_view(targets)

    assert len(view.children) == 25
    assert view.children[-1].label == "My Applications"


# --- a city closing ---------------------------------------------------------


@pytest.fixture
def deadline_watcher() -> DeadlineWatcher:
    with patch.object(DeadlineWatcher, "check_deadlines", MagicMock()):
        return DeadlineWatcher(MagicMock())


async def test_a_closed_city_drops_its_button_and_the_thread_stays_open(
    deadline_watcher,
):
    closed = _post("job-1", ["QLD"], close_date=_NOW - timedelta(days=1))
    still_open = _post("job-2", ["VIC"], minutes=1, close_date=_NOW + timedelta(days=9))
    thread = _thread()
    deadline_watcher.bot.fetch_channel = AsyncMock(return_value=thread)

    with (
        patch(
            "src.cogs.workers.deadline_watcher.job_post_db.get_by_forum_post_id",
            new=AsyncMock(return_value=[closed, still_open]),
        ),
        patch(
            "src.cogs.workers.deadline_watcher.job_post_db.mark_reminder_sent",
            new=AsyncMock(),
        ) as marked,
    ):
        await deadline_watcher._process_post(closed, _NOW)

    # Not renamed, not archived, and nothing announced in the thread.
    thread.edit.assert_not_awaited()
    thread.send.assert_not_awaited()

    view = thread.fetch_message.return_value.edit.await_args.kwargs["view"]
    assert [i.label for i in view.children] == ["Apply Now", "My Applications"]
    assert marked.await_args.args[2] is DeadlineReminder.CLOSED


async def test_the_thread_closes_when_the_last_city_does(deadline_watcher):
    closed = _post("job-1", ["QLD"], close_date=_NOW - timedelta(days=1))
    also_closed = _post(
        "job-2", ["VIC"], minutes=1, close_date=_NOW - timedelta(days=2)
    )
    thread = _thread()
    deadline_watcher.bot.fetch_channel = AsyncMock(return_value=thread)

    with (
        patch(
            "src.cogs.workers.deadline_watcher.job_post_db.get_by_forum_post_id",
            new=AsyncMock(return_value=[closed, also_closed]),
        ),
        patch.object(deadline_watcher, "_on_closed", new=AsyncMock()) as on_closed,
    ):
        await deadline_watcher._process_post(closed, _NOW)

    on_closed.assert_awaited_once()


async def test_only_the_last_city_to_close_sends_reminders(deadline_watcher):
    # Otherwise three postings of one role send three identical warnings, and
    # "closes tomorrow" is not true of the thread while a city has a week left.
    first = _post("job-1", ["QLD"], close_date=_NOW + timedelta(hours=20))
    last = _post("job-2", ["VIC"], minutes=1, close_date=_NOW + timedelta(days=9))
    thread = _thread()
    deadline_watcher.bot.fetch_channel = AsyncMock(return_value=thread)

    with (
        patch(
            "src.cogs.workers.deadline_watcher.job_post_db.get_by_forum_post_id",
            new=AsyncMock(return_value=[first, last]),
        ),
        patch.object(
            deadline_watcher, "_send_reminder", new=AsyncMock()
        ) as send_reminder,
    ):
        await deadline_watcher._process_post(first, _NOW)

    send_reminder.assert_not_awaited()


# --- a city opening later ---------------------------------------------------


async def test_a_new_city_joins_the_existing_thread():
    watcher = JobWatcher(MagicMock())
    thread = _thread()
    watcher.bot.fetch_channel = AsyncMock(return_value=thread)
    existing = _post("job-1", ["QLD"], close_date=_NOW + timedelta(days=30))

    with (
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_guild",
            new=AsyncMock(return_value=[existing]),
        ),
        patch(
            "src.cogs.workers.job_watcher.job_post_db.upsert", new=AsyncMock()
        ) as upsert,
        patch.object(watcher, "_resync_tags", new=AsyncMock()),
    ):
        attached = await watcher._attach_to_existing_thread(
            _job(["VIC"], job_id="job-2"), MagicMock(guild_id=1)
        )

    assert attached is True
    # The new listing is a row on the same thread, not a thread of its own.
    assert upsert.await_args.args[0].forum_post_id == 77
    view = thread.fetch_message.return_value.edit.await_args.kwargs["view"]
    assert [i.label for i in view.children] == [
        "Apply — QLD",
        "Apply — VIC",
        "My Applications",
    ]


async def test_a_role_whose_thread_has_finished_starts_a_new_one():
    # Every listing on the old thread closed, so it is a record of a finished
    # role. A fresh opening deserves a fresh thread rather than reviving that.
    watcher = JobWatcher(MagicMock())
    finished = _post("job-1", ["QLD"], close_date=_NOW - timedelta(days=1))

    with patch(
        "src.cogs.workers.job_watcher.job_post_db.get_by_guild",
        new=AsyncMock(return_value=[finished]),
    ):
        attached = await watcher._attach_to_existing_thread(
            _job(["VIC"], job_id="job-2"), MagicMock(guild_id=1)
        )

    assert attached is False


async def test_an_unrelated_role_does_not_join():
    watcher = JobWatcher(MagicMock())
    other = _post("job-1", ["QLD"], close_date=_NOW + timedelta(days=30))
    other.title = "Something Else"

    with patch(
        "src.cogs.workers.job_watcher.job_post_db.get_by_guild",
        new=AsyncMock(return_value=[other]),
    ):
        attached = await watcher._attach_to_existing_thread(
            _job(["VIC"], job_id="job-2"), MagicMock(guild_id=1)
        )

    assert attached is False


# --- a listing being withdrawn ----------------------------------------------


async def test_a_withdrawn_city_leaves_the_thread_standing():
    watcher = JobWatcher(MagicMock())
    thread = _thread()
    watcher.bot.fetch_channel = AsyncMock(return_value=thread)
    gone = _post("job-1", ["QLD"], close_date=_NOW - timedelta(days=1))
    still_open = _post("job-2", ["VIC"], minutes=1, close_date=_NOW + timedelta(days=9))

    with (
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_job_id",
            new=AsyncMock(return_value=[gone]),
        ),
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_forum_post_id",
            new=AsyncMock(return_value=[gone, still_open]),
        ),
        patch(
            "src.cogs.workers.job_watcher.job_post_db.delete", new=AsyncMock()
        ) as delete_record,
    ):
        await watcher._handle_delete("job-1")

    thread.delete.assert_not_called()
    thread.send.assert_not_awaited()
    delete_record.assert_awaited_once_with("job-1", 1)
    view = thread.fetch_message.return_value.edit.await_args.kwargs["view"]
    assert [i.label for i in view.children] == ["Apply Now", "My Applications"]
