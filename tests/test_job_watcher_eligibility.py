"""The watcher must not create a forum thread for a job that is not board eligible.

Discord caps a forum at 1000 active threads. The active_jobs collection holds
every job scraped, which already exceeds that, so an unfiltered watcher exhausts
the cap the first time it connects.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.mongo.collections.col_jobs import JobDocument
from src.backend.mongo.triggers import ChangeEvent, Operation
from src.cogs.workers.job_watcher import JobWatcher


def _event(operation: Operation, job: JobDocument) -> ChangeEvent:
    return ChangeEvent(
        operation=operation,
        document_id="job-1",
        full_document=job,
        raw={},
    )


@pytest.fixture
def watcher() -> JobWatcher:
    return JobWatcher(MagicMock())


@pytest.mark.parametrize(
    ("board_eligible", "should_post"),
    [
        (True, True),
        (False, False),
        (None, False),  # unscored: default-deny
    ],
)
async def test_insert_posts_only_eligible_jobs(watcher, board_eligible, should_post):
    job = JobDocument(title="Graduate Software Engineer", board_eligible=board_eligible)

    with (
        patch(
            "src.cogs.workers.job_watcher.guild_config_db.get_all",
            new=AsyncMock(return_value=[MagicMock()]),
        ),
        patch(
            "src.cogs.workers.job_watcher.post_job_to_guild",
            new=AsyncMock(return_value=True),
        ) as post,
    ):
        await watcher.on_change(_event(Operation.INSERT, job))

    assert post.called is should_post


async def test_update_for_unknown_job_does_not_post_ineligible(watcher):
    """The update path treats a job it has no thread for as an insert.

    That is the path that fires on every scrape for jobs the bot has never
    seen, so it must apply the same filter.
    """
    job = JobDocument(title="Graduate Accountant", board_eligible=False)

    with (
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_job_id",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "src.cogs.workers.job_watcher.guild_config_db.get_all",
            new=AsyncMock(return_value=[MagicMock()]),
        ),
        patch(
            "src.cogs.workers.job_watcher.post_job_to_guild",
            new=AsyncMock(return_value=True),
        ) as post,
    ):
        await watcher.on_change(_event(Operation.UPDATE, job))

    post.assert_not_called()


async def test_update_for_unknown_eligible_job_still_posts(watcher):
    job = JobDocument(title="Graduate Software Engineer", board_eligible=True)

    with (
        patch(
            "src.cogs.workers.job_watcher.job_post_db.get_by_job_id",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "src.cogs.workers.job_watcher.guild_config_db.get_all",
            new=AsyncMock(return_value=[MagicMock()]),
        ),
        patch(
            "src.cogs.workers.job_watcher.post_job_to_guild",
            new=AsyncMock(return_value=True),
        ) as post,
    ):
        await watcher.on_change(_event(Operation.UPDATE, job))

    post.assert_called_once()
