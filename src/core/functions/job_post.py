from __future__ import annotations

import logging
from collections import Counter
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
from src.core.functions.job_eligibility import (
    is_board_eligible,
    is_open_for_applications,
)
from src.core.functions.job_embed import JOB_URL, build_job_embed
from src.core.functions.job_tags import ensure_tags, select_tags

_log: Final[logging.Logger] = logging.getLogger(__name__)


_THREAD_NAME: Final[str] = "{title} | {company} [{year}]"

# MAX_SYNC_JOBS bounds how many threads one manual reconciliation may create in
# a single guild. It counts the threads the sync would actually open, not the
# size of the board: a reconciliation over a board that has legitimately grown
# past this is a no-op and must stay possible, while creating this many threads
# at once means eligibility is not being written as expected.
#
# Discord caps a guild at 1000 *active* threads -- archived ones are unlimited
# and do not count -- so the cap is a guild-wide budget shared with every other
# thread in the server, which is why the limit is counted per guild rather than
# summed across them. Recovering from a runaway sync means deleting threads by
# hand, so refuse rather than half-fill the budget and stop.
MAX_SYNC_JOBS: Final[int] = 300


def build_thread_name(title: str, company: str, year: int) -> str:
    """Return the canonical forum thread name for a job post (not truncated)."""
    return _THREAD_NAME.format(title=title, company=company, year=year)


# Audiences the weekly recap is split across. Interns and graduates want
# different postings, so each gets its own channel, its own recap and its own
# ping rather than one combined message everybody half-reads.
INTERN_AUDIENCE: Final[str] = "intern"
GRAD_AUDIENCE: Final[str] = "grad"

# Maps job type to the audience whose recap the posting belongs in. Graduate and
# professional roles share one, since the same people want both.
TYPE_TO_AUDIENCE: Final[dict[str, str]] = {
    "INTERN": INTERN_AUDIENCE,
    "GRADUATE": GRAD_AUDIENCE,
    "FULL_TIME": GRAD_AUDIENCE,
    "CONTRACT": GRAD_AUDIENCE,
    "PART_TIME": GRAD_AUDIENCE,
    "CASUAL": GRAD_AUDIENCE,
    "OTHER": GRAD_AUDIENCE,
}

# Where each audience's recap is posted, and which roles it mentions.
AUDIENCE_CHANNEL_ATTR: Final[dict[str, str]] = {
    INTERN_AUDIENCE: "intern_recap_channel_id",
    GRAD_AUDIENCE: "grad_recap_channel_id",
}

AUDIENCE_ROLE_ATTRS: Final[dict[str, tuple[str, ...]]] = {
    INTERN_AUDIENCE: ("intern_role_id",),
    GRAD_AUDIENCE: ("grad_role_id", "professional_role_id"),
}

AUDIENCE_LABEL: Final[dict[str, str]] = {
    INTERN_AUDIENCE: "internship",
    GRAD_AUDIENCE: "graduate",
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

    # Same reasoning, same place: a role whose deadline has passed cannot be
    # applied to, and posting it only for the deadline watcher to rename, tag
    # Closed and archive it on its next pass advertises dead listings and
    # churns the forum for nothing.
    if not is_open_for_applications(job):
        _log.debug(
            "Skipping closed job %r (%s) for guild %s",
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

    # No role mention here. Pinging on every post meant a notification per job,
    # which at scrape volume trains people to mute the channel and lose the
    # alerts entirely. The ping now happens once a week in the recap, which
    # collects the week's postings per audience.
    content = job_url

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
    # Closed and outdated listings are excluded in the query rather than after
    # it, so the safety limit below sizes the work that would really be done.
    # close_date: None matches a missing field too, which is what a listing with
    # no deadline looks like -- those stay postable.
    jobs = await job_col.find(
        {
            "board_eligible": True,
            "outdated": {"$ne": True},
            "$or": [
                {"close_date": None},
                {"close_date": {"$gt": datetime.now(tz=timezone.utc)}},
            ],
        },
        sort=[("_id", 1)],
    )
    if not jobs:
        _log.info("sync_jobs: no open, board-eligible jobs found in active_jobs")
        return result

    # One query for what is already posted, rather than one per (job, guild)
    # pair, so the whole job can be sized before any of it is done.
    existing_keys = {
        (post.job_id, post.guild_id) for post in await job_post_db.get_all()
    }

    pending = [
        (job, config)
        for job in jobs
        if job.id is not None
        for config in guild_configs
        if (job.id, config.guild_id) not in existing_keys
    ]

    # A reconciliation that wants to create an implausible number of threads is
    # a symptom of something wrong upstream -- eligibility not written, or the
    # scraper re-keying the collection -- not an instruction. Discord caps a
    # forum at 1000 active threads, so refuse rather than half-fill it and stop.
    #
    # The limit counts threads to open, not eligible jobs: reconciling a board
    # that has legitimately grown past it creates nothing and has to stay
    # possible, or /jobs sync breaks for good once the board fills up.
    #
    # It is counted per guild because that is the unit being protected: the
    # 1000-active-thread cap is a guild-wide budget, and each guild has its own.
    # Summing across guilds would instead make the limit stricter the more
    # servers the bot is in, so adding a second guild would halve what either
    # one may sync, for no reason to do with any real cap.
    per_guild = Counter(config.guild_id for _, config in pending)
    over_limit = {
        guild_id: count
        for guild_id, count in per_guild.items()
        if count > MAX_SYNC_JOBS
    }
    if over_limit:
        _log.error(
            "sync_jobs: refusing to sync. %s exceeds the safety limit of %d new "
            "threads per guild. Check that the scraper is writing "
            "board_eligible correctly before retrying.",
            ", ".join(
                f"guild {guild_id} would get {count} new threads"
                for guild_id, count in sorted(over_limit.items())
            ),
            MAX_SYNC_JOBS,
        )
        result.aborted = True
        return result

    result.skipped = sum(
        1
        for job in jobs
        if job.id is not None
        for config in guild_configs
        if (job.id, config.guild_id) in existing_keys
    )

    for job, config in pending:
        posted = await post_job_to_guild(bot, job, config)
        if posted:
            result.posted += 1
        else:
            result.skipped += 1
        if on_progress:
            await on_progress(result)

    _log.info("sync_jobs complete: posted=%d skipped=%d", result.posted, result.skipped)
    return result
