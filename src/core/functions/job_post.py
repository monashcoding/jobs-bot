from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from discord.ext import commands

from src.backend.mongo.collections.col_jobs import JobDocument, job_col
from src.backend.sql.models import GuildConfig, JobPost
from src.backend.sql.tables import guild_config_db, job_post_db
from src.core.functions.job_embed import build_job_embed

_log = logging.getLogger(__name__)


async def post_job_to_guild(
    bot: commands.Bot,
    job: JobDocument,
    config: GuildConfig,
) -> bool:
    """Create a forum thread for *job* in the guild described by *config*.

    Upserts the resulting JobPost record in SQL.
    Returns True if the thread was created, False if skipped or failed.
    """
    try:
        channel = bot.get_channel(config.forum_channel_id)
        if channel is None:
            channel = await bot.fetch_channel(config.forum_channel_id)
    except discord.NotFound:
        _log.warning(
            "Forum channel %s not found for guild %s",
            config.forum_channel_id,
            config.guild_id,
        )
        return False
    except Exception:  # noqa: BLE001
        _log.exception(
            "Failed to fetch forum channel %s for guild %s",
            config.forum_channel_id,
            config.guild_id,
        )
        return False

    if not isinstance(channel, discord.ForumChannel):
        _log.warning(
            "Channel %s for guild %s is not a ForumChannel",
            config.forum_channel_id,
            config.guild_id,
        )
        return False

    embed = build_job_embed(job)
    try:
        thread, _ = await channel.create_thread(
            name=f"{job.title} | {job.company.name}"[:100],
            content=f"https://jobs.monashcoding.com/jobs/{job.id}",
            embed=embed,
            auto_archive_duration=10080,
        )
    except Exception:  # noqa: BLE001
        _log.exception(
            "Failed to create forum thread in channel %s for guild %s",
            config.forum_channel_id,
            config.guild_id,
        )
        return False

    post = JobPost(
        job_id=job.id,
        guild_id=config.guild_id,
        forum_post_id=thread.id,
        forum_channel_id=channel.id,
        posted_at=datetime.now(tz=timezone.utc),
    )
    await job_post_db.upsert(post)
    _log.info(
        "Created forum thread %s for job %s in guild %s",
        thread.id,
        job.id,
        config.guild_id,
    )
    return True


@dataclass
class SyncResult:
    posted: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.posted + self.skipped


async def sync_jobs(bot: commands.Bot) -> SyncResult:
    """Reconcile MongoDB active_jobs with Discord forum posts.

    For every (job, guild_config) pair that has no JobPost record, creates a
    forum thread and inserts the record. Already-posted jobs are skipped.

    Returns a SyncResult with counts of posted and skipped jobs.
    """
    result = SyncResult()

    guild_configs = await guild_config_db.get_all()
    if not guild_configs:
        _log.info("sync_jobs: no guild configs configured, nothing to sync")
        return result

    jobs = await job_col.find({})
    if not jobs:
        _log.info("sync_jobs: no jobs found in active_jobs collection")
        return result

    for job in jobs:
        if job.id is None:
            continue
        for config in guild_configs:
            existing = await job_post_db.get(job.id, config.guild_id)
            if existing is not None:
                result.skipped += 1
                continue
            posted = await post_job_to_guild(bot, job, config)
            if posted:
                result.posted += 1
            else:
                result.skipped += 1

    _log.info("sync_jobs complete: posted=%d skipped=%d", result.posted, result.skipped)
    return result
