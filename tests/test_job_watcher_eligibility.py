"""The watcher must not create a forum thread for a job that is not board eligible.

Discord caps a forum at 1000 active threads. The active_jobs collection holds
every job scraped, which already exceeds that, so an unfiltered watcher exhausts
the cap the first time it connects.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
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


# post_job_to_guild is the choke point every thread-creating path goes through.
# The manual /jobs sync reconciliation calls it directly, walking the whole
# collection, so a gate that lived only in the watcher would not protect it.
async def test_post_job_to_guild_refuses_ineligible_job():
    from src.core.functions.job_post import post_job_to_guild

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=MagicMock())
    config = MagicMock()
    config.guild_id = 1

    job = JobDocument(title="Graduate Accountant", board_eligible=False)
    assert await post_job_to_guild(bot, job, config) is False
    # It must bail before touching Discord at all.
    bot.get_channel.assert_not_called()


async def test_post_job_to_guild_refuses_unscored_job():
    from src.core.functions.job_post import post_job_to_guild

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=MagicMock())
    config = MagicMock()
    config.guild_id = 1

    job = JobDocument(title="Graduate Software Engineer")  # no board_eligible
    assert await post_job_to_guild(bot, job, config) is False
    bot.get_channel.assert_not_called()


# A reconciliation that wants to create thousands of threads is a symptom of
# something wrong upstream, not an instruction to fill the forum.
async def test_sync_jobs_aborts_above_the_safety_limit():
    from src.core.functions import job_post

    too_many = []
    for i in range(job_post.MAX_SYNC_JOBS + 1):
        job = JobDocument(title=f"Job {i}", board_eligible=True)
        job.id = str(i)
        too_many.append(job)

    with (
        patch.object(
            job_post.guild_config_db,
            "get_all",
            new=AsyncMock(return_value=[MagicMock(guild_id=1)]),
        ),
        patch.object(job_post.job_col, "find", new=AsyncMock(return_value=too_many)),
        patch.object(job_post.job_post_db, "get_all", new=AsyncMock(return_value=[])),
        patch.object(
            job_post, "post_job_to_guild", new=AsyncMock(return_value=True)
        ) as post,
    ):
        result = await job_post.sync_jobs(MagicMock())

    assert result.aborted is True
    assert result.posted == 0
    post.assert_not_called()


# The limit bounds the threads a sync would create, not the size of the board.
# Reconciling a board that has legitimately grown past the limit is a no-op and
# has to stay possible, or /jobs sync breaks permanently once the board fills.
async def test_sync_over_the_limit_is_allowed_when_everything_is_already_posted():
    from src.core.functions import job_post

    jobs = []
    for i in range(job_post.MAX_SYNC_JOBS + 1):
        job = JobDocument(title=f"Job {i}", board_eligible=True)
        job.id = str(i)
        jobs.append(job)

    already_posted = [MagicMock(job_id=job.id, guild_id=1) for job in jobs]

    with (
        patch.object(
            job_post.guild_config_db,
            "get_all",
            new=AsyncMock(return_value=[MagicMock(guild_id=1)]),
        ),
        patch.object(job_post.job_col, "find", new=AsyncMock(return_value=jobs)),
        patch.object(
            job_post.job_post_db, "get_all", new=AsyncMock(return_value=already_posted)
        ),
        patch.object(
            job_post, "post_job_to_guild", new=AsyncMock(return_value=True)
        ) as post,
    ):
        result = await job_post.sync_jobs(MagicMock())

    assert result.aborted is False
    assert result.posted == 0
    assert result.skipped == len(jobs)
    post.assert_not_called()


async def test_sync_jobs_queries_only_eligible_jobs():
    from src.core.functions import job_post

    find = AsyncMock(return_value=[])
    with (
        patch.object(
            job_post.guild_config_db,
            "get_all",
            new=AsyncMock(return_value=[MagicMock()]),
        ),
        patch.object(job_post.job_col, "find", new=find),
    ):
        await job_post.sync_jobs(MagicMock())

    # active_jobs holds every job ever scraped; the filter must be in the query.
    assert find.call_args.args[0] == {"board_eligible": True}


# Job posts no longer ping. A notification per job at scrape volume trains
# people to mute the channel, which loses the alerts entirely.
async def test_job_post_content_has_no_role_mention():
    from src.core.functions import job_post

    captured = {}

    async def fake_create_thread(**kwargs):
        captured.update(kwargs)
        thread = MagicMock()
        thread.id = 5
        return thread, MagicMock(id=6)

    channel = MagicMock(spec=discord.ForumChannel)
    channel.create_thread = fake_create_thread

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=channel)

    config = MagicMock()
    config.guild_id = 1
    config.intern_role_id = 42
    config.grad_role_id = 43

    job = JobDocument(
        title="Graduate Software Engineer", type="INTERN", board_eligible=True
    )
    job.id = "507f1f77bcf86cd799439011"

    with (
        patch.object(job_post, "ensure_tags", new=AsyncMock(return_value={})),
        patch.object(job_post, "select_tags", new=MagicMock(return_value=[])),
        patch.object(job_post.job_post_db, "upsert", new=AsyncMock()),
    ):
        await job_post.post_job_to_guild(bot, job, config)

    assert "<@&" not in captured.get("content", ""), (
        f"job post still pings a role: {captured.get('content')!r}"
    )


# Discord's 1000-active-thread cap is a per-guild budget, and each guild has its
# own, so the limit is counted per guild. Summing across guilds would make the
# limit stricter the more servers the bot is in: adding a second guild would
# halve what either one is allowed to sync, for no reason to do with the cap.
async def test_sync_limit_is_per_guild_not_summed_across_guilds():
    from src.core.functions import job_post

    # Two guilds, each needing two-thirds of the limit. Summed that is over;
    # per guild neither is, and neither guild is close to Discord's cap.
    per_guild = (job_post.MAX_SYNC_JOBS * 2) // 3
    jobs = []
    for i in range(per_guild):
        job = JobDocument(title=f"Job {i}", board_eligible=True)
        job.id = str(i)
        jobs.append(job)

    with (
        patch.object(
            job_post.guild_config_db,
            "get_all",
            new=AsyncMock(return_value=[MagicMock(guild_id=1), MagicMock(guild_id=2)]),
        ),
        patch.object(job_post.job_col, "find", new=AsyncMock(return_value=jobs)),
        patch.object(job_post.job_post_db, "get_all", new=AsyncMock(return_value=[])),
        patch.object(
            job_post, "post_job_to_guild", new=AsyncMock(return_value=True)
        ) as post,
    ):
        result = await job_post.sync_jobs(MagicMock())

    assert result.aborted is False
    assert result.posted == per_guild * 2
    assert post.await_count == per_guild * 2


async def test_sync_aborts_when_a_single_guild_is_over_the_limit():
    from src.core.functions import job_post

    jobs = []
    for i in range(job_post.MAX_SYNC_JOBS + 1):
        job = JobDocument(title=f"Job {i}", board_eligible=True)
        job.id = str(i)
        jobs.append(job)

    # Guild 2 already has every thread; only guild 1 is over the limit, and one
    # guild over it is enough to refuse the whole sync.
    already_posted = [MagicMock(job_id=job.id, guild_id=2) for job in jobs]

    with (
        patch.object(
            job_post.guild_config_db,
            "get_all",
            new=AsyncMock(return_value=[MagicMock(guild_id=1), MagicMock(guild_id=2)]),
        ),
        patch.object(job_post.job_col, "find", new=AsyncMock(return_value=jobs)),
        patch.object(
            job_post.job_post_db, "get_all", new=AsyncMock(return_value=already_posted)
        ),
        patch.object(
            job_post, "post_job_to_guild", new=AsyncMock(return_value=True)
        ) as post,
    ):
        result = await job_post.sync_jobs(MagicMock())

    assert result.aborted is True
    post.assert_not_called()
