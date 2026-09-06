"""fix-tags re-derives every tag, not just Open/Closed.

It used to carry the existing tags across untouched and correct only the status,
so a thread posted under older tagging rules kept those tags forever. The one
command whose job is to make the board match the code has to actually do that.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.backend.mongo.collections.col_jobs import JobDocument
from src.backend.sql.models import JobPost
from src.cogs.commands.jobs import JobsGroup

_CHANNEL_TAGS = (
    "Open",
    "Closed",
    "Intern/Student",
    "Graduate",
    "Professional",
    "Melbourne",
    "Sydney",
    "Other",
    "AU Citizen/PR",
    "NZ Citizen/PR",
    "International",
    "Anyone Can Apply",
    "Other Rights",
    "2026",
)


def _tag(name: str) -> MagicMock:
    tag = MagicMock()
    tag.name = name
    tag.delete = AsyncMock()
    return tag


def _post() -> JobPost:
    return JobPost(
        job_id="job-1",
        guild_id=1,
        forum_post_id=99,
        forum_channel_id=3,
        posted_at=datetime.now(tz=timezone.utc),
        title="Grad Software Engineer",
        close_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
    )


def _job() -> JobDocument:
    return JobDocument(
        title="Grad Software Engineer",
        type="GRADUATE",
        locations=["NSW"],
        working_rights=["AUS_CITIZEN_PR", "NZ_CITIZEN_PR", "INTERNATIONAL"],
    )


def _thread(*applied: str) -> MagicMock:
    thread = MagicMock()
    thread.id = 99
    thread.parent_id = 3
    thread.archived = False
    thread.applied_tags = [_tag(n) for n in applied]
    parent = MagicMock()
    parent.available_tags = [_tag(n) for n in _CHANNEL_TAGS]
    thread.parent = parent
    thread.edit = AsyncMock()
    return thread


async def _run(thread: MagicMock, jobs: dict, forums: list | None = None) -> MagicMock:
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()

    async def fetch_channel(channel_id: int):
        if forums and channel_id == 3:
            return forums[0]
        return thread

    interaction.client.fetch_channel = AsyncMock(side_effect=fetch_channel)

    configs = [MagicMock(forum_channel_id=3)] if forums else []
    with (
        patch(
            "src.cogs.commands.jobs.job_post_db.get_all",
            new=AsyncMock(return_value=[_post()]),
        ),
        patch(
            "src.cogs.commands.jobs.fetch_board_eligible_ids",
            new=AsyncMock(return_value={"job-1"}),
        ),
        patch(
            "src.cogs.commands.jobs.job_col.get_many",
            new=AsyncMock(return_value=jobs),
        ),
        patch(
            "src.cogs.commands.jobs.guild_config_db.get_all",
            new=AsyncMock(return_value=configs),
        ),
    ):
        await JobsGroup.fix_tags.callback(JobsGroup(), interaction)
    return interaction


def _applied(thread: MagicMock) -> list[str]:
    for call in reversed(thread.edit.await_args_list):
        if "applied_tags" in call.kwargs:
            return [t.name for t in call.kwargs["applied_tags"]]
    return []


async def test_tags_are_rederived_from_the_job_document():
    thread = _thread("Open", "Graduate", "Sydney", "2026", "AU Citizen/PR")

    await _run(thread, {"job-1": _job()})

    names = _applied(thread)
    assert names[0] == "Open"
    assert "Anyone Can Apply" in names
    assert "2026" not in names
    assert "AU Citizen/PR" not in names


async def test_a_thread_already_correct_is_not_edited():
    thread = _thread("Open", "Graduate", "Sydney", "Anyone Can Apply")

    await _run(thread, {"job-1": _job()})

    thread.edit.assert_not_awaited()


async def test_a_thread_without_a_document_keeps_its_tags():
    # The job left the collection but the thread is still up: there is nothing
    # to re-derive from, so only the status is corrected.
    thread = _thread("Closed", "Graduate", "Sydney", "AU Citizen/PR")

    await _run(thread, {})

    names = _applied(thread)
    assert names[0] == "Open"
    assert "AU Citizen/PR" in names


async def test_retired_year_tags_are_deleted_from_the_forum():
    # Deleting the tag strips it from every thread at once, archived ones
    # included, and removes it from the forum's filter bar.
    forum = MagicMock(spec=discord.ForumChannel)
    forum.id = 3
    forum.available_tags = [_tag(n) for n in _CHANNEL_TAGS]
    thread = _thread("Open", "Graduate", "Sydney", "Anyone Can Apply")

    interaction = await _run(thread, {"job-1": _job()}, forums=[forum])

    deleted = [t.name for t in forum.available_tags if t.delete.await_count]
    assert deleted == ["2026"]
    assert "retired tag" in interaction.followup.send.await_args.args[0]


@pytest.mark.parametrize("name", ["Open", "Graduate", "Sydney", "Featured", "Round 2"])
async def test_only_bare_years_are_treated_as_retired(name):
    forum = MagicMock(spec=discord.ForumChannel)
    forum.id = 3
    forum.available_tags = [_tag(name)]
    thread = _thread("Open", "Graduate", "Sydney", "Anyone Can Apply")

    await _run(thread, {"job-1": _job()}, forums=[forum])

    forum.available_tags[0].delete.assert_not_awaited()
