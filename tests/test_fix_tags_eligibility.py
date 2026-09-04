"""fix-tags reopened threads for jobs the board filter excludes.

It decided archive state from the close date alone, so any ineligible job whose
deadline had not passed counted as "open" and got unarchived -- undoing the
board filter every time someone ran the command.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.sql.models import JobPost
from src.cogs.commands.jobs import JobsGroup


def _tag(name: str) -> MagicMock:
    tag = MagicMock()
    tag.name = name
    return tag


def _post(job_id: str) -> JobPost:
    return JobPost(
        job_id=job_id,
        guild_id=1,
        forum_post_id=99,
        forum_channel_id=3,
        posted_at=datetime.now(tz=timezone.utc),
        title="Grad Software Engineer",
        # Deadline well in the future: by close date alone this reads as open.
        close_date=datetime.now(tz=timezone.utc) + timedelta(days=30),
    )


def _thread() -> MagicMock:
    thread = MagicMock()
    thread.id = 99
    thread.parent_id = 3
    thread.archived = True
    thread.applied_tags = [_tag("Closed")]
    parent = MagicMock()
    parent.available_tags = [_tag("Open"), _tag("Closed")]
    thread.parent = parent
    thread.edit = AsyncMock()
    return thread


async def _run_fix_tags(job_id: str, eligible_ids: set[str]) -> MagicMock:
    thread = _thread()

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    interaction.client.fetch_channel = AsyncMock(return_value=thread)

    with (
        patch(
            "src.cogs.commands.jobs.job_post_db.get_all",
            new=AsyncMock(return_value=[_post(job_id)]),
        ),
        patch(
            "src.cogs.commands.jobs.fetch_board_eligible_ids",
            new=AsyncMock(return_value=eligible_ids),
        ),
    ):
        await JobsGroup.fix_tags.callback(JobsGroup(), interaction)

    return thread


def _final_archive_state(thread: MagicMock) -> bool | None:
    """The archived value of the last edit that set one."""
    for call in reversed(thread.edit.await_args_list):
        if "archived" in call.kwargs:
            return call.kwargs["archived"]
    return None


async def test_ineligible_job_thread_is_left_archived():
    thread = await _run_fix_tags("job-1", eligible_ids=set())

    assert _final_archive_state(thread) is True, (
        "a job the board filter excludes must not be unarchived back onto the board"
    )


async def test_eligible_open_job_thread_is_still_reopened():
    # The filter must not break the command's actual purpose.
    thread = await _run_fix_tags("job-1", eligible_ids={"job-1"})

    assert _final_archive_state(thread) is False


async def test_job_missing_from_mongo_is_left_archived():
    # Not in the eligible set because it is not in the collection at all.
    thread = await _run_fix_tags("deleted-job", eligible_ids={"some-other-job"})

    assert _final_archive_state(thread) is True
