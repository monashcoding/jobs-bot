from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

import discord
from discord.ext import commands

from src.backend.mongo.collections.col_jobs import JobDocument, job_col
from src.backend.sql.models import GuildConfig, JobPost
from src.backend.sql.tables import guild_config_db, job_post_db
from src.core import emojis
from src.core.functions.company_emoji import get_company_emoji
from src.core.functions.job_eligibility import is_board_eligible
from src.core.functions.job_embed import JOB_URL, build_job_embed
from src.core.functions.job_tags import ensure_tags, select_tags

_log: Final[logging.Logger] = logging.getLogger(__name__)


_THREAD_NAME: Final[str] = "{title} | {company} [{year}]"

# MAX_SYNC_JOBS bounds a manual reconciliation. The scraper caps the board well
# below this, so reaching it means eligibility is not being written as expected;
# a Discord forum holds 1000 active threads and recovering from a runaway sync
# means deleting them by hand.
MAX_SYNC_JOBS: Final[int] = 300


def build_thread_name(title: str, company: str, year: int) -> str:
    """Return the canonical forum thread name for a job post (not truncated)."""
    return _THREAD_NAME.format(title=title, company=company, year=year)


# Maps job type to the GuildConfig attribute holding the notification role ID.
_TYPE_TO_ROLE_ATTR: Final[dict[str, str]] = {
    "INTERN": "intern_role_id",
    "GRADUATE": "grad_role_id",
    "FULL_TIME": "professional_role_id",
    "CONTRACT": "professional_role_id",
    "PART_TIME": "professional_role_id",
    "CASUAL": "professional_role_id",
    "OTHER": "professional_role_id",
}


async def post_job_to_guild(
    bot: commands.Bot,
    job: JobDocument,
    config: GuildConfig,
) -> bool:
    """Create a forum thread for *job* in the guild described by *config*.

    Upserts the resulting JobPost record in SQL.
    Returns True if the thread was created, False if skipped or failed.
    """
    # The authoritative eligibility gate. Every path that creates a thread goes
    # through this function -- the change stream watcher and the manual
    # /jobs sync reconciliation -- so the check belongs here rather than only at
    # the callers. sync_jobs walks the entire collection, so a gate it did not
    # inherit would post thousands of threads the first time anyone ran it.
    if not is_board_eligible(job):
        _log.debug(
            "Skipping ineligible job %r (%s) for guild %s",
            job.title,
            job.company.name,
            config.guild_id,
        )
        return False

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

    tag_map = await ensure_tags(channel, job)
    tags = select_tags(job, tag_map)

    embed = build_job_embed(job)

    job_url = JOB_URL.format(job_id=job.id)
    role_id: int | None = None
    if job.type:
        role_attr = _TYPE_TO_ROLE_ATTR.get(job.type)
        if role_attr:
            role_id = getattr(config, role_attr, None)
    content = f"<@&{role_id}> {job_url}" if role_id else job_url

    apply_view = discord.ui.View()
    apply_view.add_item(
        discord.ui.Button(
            label="Apply Now", url=job_url, style=discord.ButtonStyle.link
        )
    )
    apply_view.add_item(
        discord.ui.Button(
            label="My Applications",
            url="https://jobs.monashcoding.com/my-applications?ref=discord-bot",
            style=discord.ButtonStyle.link,
        )
    )

    try:
        year_dt = (
            job.close_date
            or job.updated_at
            or job.created_at
            or datetime.now(tz=timezone.utc)
        )
        thread, starter_message = await channel.create_thread(
            name=build_thread_name(job.title, job.company.name, year_dt.year)[:100],
            content=content,
            embed=embed,
            view=apply_view,
            applied_tags=tags,
            auto_archive_duration=10080,
        )
    except Exception:  # noqa: BLE001
        _log.exception(
            "Failed to create forum thread in channel %s for guild %s",
            config.forum_channel_id,
            config.guild_id,
        )
        return False

    company_emoji = get_company_emoji(job.company.name) or emojis.MAC_EMPLOYED
    try:
        await starter_message.add_reaction(company_emoji)
    except Exception:  # noqa: BLE001
        _log.warning(
            "Failed to react with emoji %s on thread %s",
            company_emoji,
            thread.id,
        )

    post = JobPost(
        job_id=job.id,
        guild_id=config.guild_id,
        forum_post_id=thread.id,
        forum_channel_id=channel.id,
        posted_at=datetime.now(tz=timezone.utc),
        title=job.title,
        job_type=job.type,
        application_url=job.application_url,
        one_liner=job.one_liner,
        description=job.description,
        close_date=job.close_date,
        industry_field=job.industry_field,
        is_sponsored=job.is_sponsored,
        outdated=job.outdated,
        source=job.source,
        version=job.version,
        wfh_status=job.wfh_status,
        days_lived=job.days_lived,
        fingerprint=job.fingerprint,
        locations=job.locations,
        source_urls=job.source_urls,
        study_fields=job.study_fields,
        working_rights=job.working_rights,
        company_name=job.company.name,
        company_website=job.company.website,
        company_logo=job.company.logo,
        job_created_at=job.created_at,
        job_updated_at=job.updated_at,
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
    # aborted is set when the safety limit refused the sync outright, so the
    # caller can say so instead of reporting a successful sync of nothing.
    aborted: bool = False

    @property
    def total(self) -> int:
        return self.posted + self.skipped


async def sync_jobs(
    bot: commands.Bot,
    on_progress: Callable[[SyncResult], Awaitable[None]] | None = None,
) -> SyncResult:
    """Reconcile MongoDB active_jobs with Discord forum posts.

    For every (job, guild_config) pair that has no JobPost record, creates a
    forum thread and inserts the record. Already-posted jobs are skipped.

    on_progress is called after every (job, guild) pair is processed. The
    caller decides whether to act on it (e.g. throttle edits by elapsed time).

    Returns a SyncResult with counts of posted and skipped jobs.
    """
    result = SyncResult()

    guild_configs = await guild_config_db.get_all()
    if not guild_configs:
        _log.info("sync_jobs: no guild configs configured, nothing to sync")
        return result

    # Ask the database for the eligible jobs rather than filtering the whole
    # collection in memory: active_jobs holds every job ever scraped, and only a
    # small fraction of it belongs on the board.
    jobs = await job_col.find({"board_eligible": True}, sort=[("_id", 1)])
    if not jobs:
        _log.info("sync_jobs: no board-eligible jobs found in active_jobs")
        return result

    # A reconciliation that wants to create an implausible number of threads is
    # a symptom of something wrong upstream -- eligibility not written, or the
    # scraper re-keying the collection -- not an instruction. Discord caps a
    # forum at 1000 active threads, so refuse rather than half-fill it and stop.
    if len(jobs) > MAX_SYNC_JOBS:
        _log.error(
            "sync_jobs: refusing to sync %d eligible jobs, which exceeds the "
            "safety limit of %d. Check that the scraper is writing "
            "board_eligible correctly before retrying.",
            len(jobs),
            MAX_SYNC_JOBS,
        )
        result.aborted = True
        return result

    for job in jobs:
        if job.id is None:
            continue
        for config in guild_configs:
            existing = await job_post_db.get(job.id, config.guild_id)
            if existing is not None:
                result.skipped += 1
            else:
                posted = await post_job_to_guild(bot, job, config)
                if posted:
                    result.posted += 1
                else:
                    result.skipped += 1
            if on_progress:
                await on_progress(result)

    _log.info("sync_jobs complete: posted=%d skipped=%d", result.posted, result.skipped)
    return result
