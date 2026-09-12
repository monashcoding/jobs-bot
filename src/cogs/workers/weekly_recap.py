from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from src.backend.sql.models import GuildConfig, JobPost
from src.backend.sql.tables import guild_config_db, job_post_db
from src.config import RECAP_DAY, RECAP_HOUR, RECAP_TIMEZONE
from src.core.functions.company_rank import normalise_company, recap_rank
from src.core.functions.forum_threads import thread_reply_counts
from src.core.functions.job_groups import live_posts, primary_post
from src.core.functions.job_post import (
    AUDIENCE_CHANNEL_ATTR,
    AUDIENCE_LABEL,
    AUDIENCE_ROLE_ATTRS,
    GRAD_AUDIENCE,
    INTERN_AUDIENCE,
    TYPE_TO_AUDIENCE,
)

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Resolved once at import so a missing time zone database fails loudly here,
# rather than raising inside the task loop where a dead loop looks identical to
# a quiet week.
RECAP_ZONE: Final[ZoneInfo] = ZoneInfo(RECAP_TIMEZONE)

# The recap is a prompt to go and look at the board, not an inventory of it. The
# heading already carries the full count, so the list below it only has to be
# long enough to be worth reading -- a wall of links is the same noise a
# notification per posting was, and gets muted the same way.
#
# Ten *companies*, not ten postings: the list names employers, and a company
# hiring for three roles this week earns one line, not three.
_MAX_LISTED: Final[int] = 10

# Discord rejects messages over 2000 characters. Ten company names do not come
# close, so this is a backstop against a pathological name rather than the thing
# that shapes the message.
_MAX_MESSAGE_LENGTH: Final[int] = 1900

# Room kept free so the "and N more" line always fits, whatever the entries did
# to the budget. A dropped count is worse than a dropped entry: it is the only
# thing telling the reader the list is partial.
_OVERFLOW_RESERVE: Final[int] = 120

# Replies at or below this do not count at all. The bot posts up to four
# deadline warnings into a thread and a closing notice after them, and every one
# of those draws real answers -- "is this still open?", "applied, good luck" --
# so a role about to close collects a handful of messages for reasons that have
# nothing to do with how interesting it is. Discounting the bot's own messages
# is not enough on its own, because the replies to them are genuine messages
# from real people. Past this, a thread is one somebody actually wanted to talk
# about.
_REPLY_FLOOR: Final[int] = 4

# A guild that received a recap more recently than this does not get another.
# Shorter than a week so a deploy that shifts the run by a few hours still
# fires, long enough that repeated restarts inside the recap hour cannot ping
# twice.
_MIN_RECAP_GAP: Final[timedelta] = timedelta(days=6)


def audience_for(job_type: str | None) -> str:
    """Return the recap audience a posting belongs to.

    An unknown or missing type falls to the graduate recap rather than being
    dropped: interns are the narrower audience, so a misfiled graduate posting
    is a smaller mistake than a silently missing one.
    """
    if job_type is None:
        return GRAD_AUDIENCE
    return TYPE_TO_AUDIENCE.get(job_type, GRAD_AUDIENCE)


def threads_of(posts: list[JobPost]) -> dict[int, list[JobPost]]:
    """Group listings by the thread they share, oldest thread first.

    A role advertised in three states is three rows against one forum post, and
    the recap counts and links threads, not listings.
    """
    by_thread: dict[int, list[JobPost]] = {}
    for post in posts:
        by_thread.setdefault(post.forum_post_id, []).append(post)
    return by_thread


def one_per_thread(posts: list[JobPost]) -> list[JobPost]:
    """Collapse listings that share a thread down to the thread's own post."""
    return [primary_post(group) for group in threads_of(posts).values()]


def thread_scores(posts: list[JobPost], replies: dict[int, int]) -> dict[int, int]:
    """Return how much conversation each thread actually drew.

    The reply count Discord reports includes the bot's own deadline messages,
    and a role closing this week collects several of them. Left uncorrected, a
    thread nobody spoke in outranks one people did purely because the deadline
    watcher warned about it three times.

    Those messages are exactly the reminder stages recorded on the listing, one
    message each (``deadline_watcher``), so the union across the thread's rows
    is the bot's own contribution and comes back off the count. What is left has
    to clear ``_REPLY_FLOOR`` to count as conversation at all, because the
    replies *to* those warnings are real messages that say nothing about the
    role.
    """
    scores: dict[int, int] = {}
    for thread_id, rows in threads_of(posts).items():
        own = {stage for row in rows for stage in row.deadline_reminders_sent}
        replied = max(replies.get(thread_id, 0) - len(own), 0)
        scores[thread_id] = replied if replied > _REPLY_FLOOR else 0
    return scores


@dataclass(frozen=True)
class CompanyEntry:
    """One employer's line in the recap."""

    # The employer as the bot knows it. The rendered line shows the thread's
    # own name instead, which already starts with the company; this is what the
    # entry is grouped and ordered as.
    name: str
    thread_id: int
    score: int
    # How many of the week's open threads this employer owns. The line links
    # one of them, so the count is what tells the reader there are others.
    roles: int
    rank: tuple[int, int]


def company_entries(
    threads: dict[int, list[JobPost]], scores: dict[int, int]
) -> list[CompanyEntry]:
    """Collapse threads to one entry per employer, most popular first.

    The list names companies, so two roles from one company are one line: a
    reader scanning for names gets ten employers rather than the same one three
    times. The line links that company's busiest thread, because the count
    beside it is already saying there is more than one.

    Entries are ordered by prominence first and conversation second. A big name
    is the reason someone opens the message, and a closing role draws messages
    whatever employer it is from, so engagement can reorder equally prominent
    employers but never promote one over a bigger one.
    """
    entries: dict[str, CompanyEntry] = {}

    for thread_id, rows in threads.items():
        primary = primary_post(rows)
        # An empty company name keys on the thread rather than merging every
        # nameless posting into one blank line.
        key = normalise_company(primary.company_name) or f"thread:{thread_id}"
        score = scores.get(thread_id, 0)
        entry = CompanyEntry(
            # The board's own titles are the fallback, so a line is never blank.
            name=primary.company_name.strip() or primary.title,
            thread_id=thread_id,
            score=score,
            roles=1,
            rank=recap_rank(primary.company_tier, primary.company_name),
        )

        if (existing := entries.get(key)) is None:
            entries[key] = entry
            continue

        # Threads arrive oldest first, so a strict improvement is what moves
        # the link: an equally busy thread keeps the earlier one.
        better = entry if score > existing.score else existing
        entries[key] = CompanyEntry(
            name=better.name,
            thread_id=better.thread_id,
            score=better.score,
            roles=existing.roles + 1,
            rank=better.rank,
        )

    # Stable, so employers that tie on every key keep the order the query
    # returned their threads in, oldest first.
    return sorted(entries.values(), key=lambda entry: (entry.rank, -entry.score))


def build_recap(
    posts: list[JobPost],
    audience: str,
    mentions: str,
    forum_channel_id: int,
    replies: dict[int, int] | None = None,
) -> str:
    """Render one audience's recap message."""
    threads = threads_of(posts)
    scores = thread_scores(posts, replies or {})

    # The heading is the week's volume, so it counts everything posted. The
    # list is what someone can still act on, so it does not: a role posted on
    # Monday that closed on Wednesday has had its apply buttons retired and its
    # thread archived, and linking it spends one of ten slots on a dead end --
    # closed threads being, if anything, the ones with the most replies.
    open_threads = {
        thread_id: rows for thread_id, rows in threads.items() if live_posts(rows)
    }

    label = AUDIENCE_LABEL[audience]
    count = len(threads)
    heading = f"{mentions} **{count} new {label} role{'s' if count != 1 else ''} this week!**".strip()

    lines = [heading, ""]
    length = len(heading) + 1

    entries = company_entries(open_threads, scores)
    if entries:
        intro = "Here are the most popular:"
        lines.append(intro)
        length += len(intro) + 1

    listed_roles = 0

    for position, entry in enumerate(entries[:_MAX_LISTED], start=1):
        # A thread mention rather than a hand-built URL: Discord renders it as
        # the thread's own name, which now leads with the employer and carries
        # the role after it, so the line needs nothing in front of it.
        suffix = f" ({entry.roles} roles)" if entry.roles > 1 else ""
        line = f"{position}. <#{entry.thread_id}>{suffix}"
        if length + len(line) + 1 > _MAX_MESSAGE_LENGTH - _OVERFLOW_RESERVE:
            break
        lines.append(line)
        length += len(line) + 1
        listed_roles += entry.roles

    # Always a real channel link: the line exists to send people somewhere, and
    # naming the board without linking it makes them go and find it. The
    # remainder counts open threads the listed companies do not already
    # account for, so a listed employer's second role is not also "more".
    remaining = len(open_threads) - listed_roles
    if remaining > 0:
        lines.append(f"and {remaining} more in <#{forum_channel_id}>.")
    elif not entries:
        lines.append(f"See them all in <#{forum_channel_id}>.")

    return "\n".join(lines)


def role_mentions(config: GuildConfig, audience: str) -> str:
    """Return the role mentions for an audience, skipping unconfigured roles."""
    mentions = []
    for attr in AUDIENCE_ROLE_ATTRS[audience]:
        role_id = getattr(config, attr, None)
        if role_id:
            mentions.append(f"<@&{role_id}>")
    return " ".join(mentions)


class WeeklyRecap(commands.Cog):
    """Posts one recap per audience per week, and is the only thing that pings.

    Job posts themselves no longer mention a role. At scrape volume a ping per
    posting is a notification per job, which trains people to mute the channel
    and lose the alerts altogether. Collecting the week into one message per
    audience keeps the signal without the noise.

    It runs Friday evening, when people have time to read it and the weekend to
    act on it, rather than landing mid-week alongside everything else.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.recap.start()

    def cog_unload(self) -> None:
        self.recap.cancel()

    @tasks.loop(hours=1)
    async def recap(self) -> None:
        now = datetime.now(tz=timezone.utc)

        # Compare in the configured zone, so the recap stays at the same local
        # hour across daylight saving rather than drifting with the container's
        # UTC clock. The loop ticks hourly and fires on the matching day and
        # hour, so a restart cannot skip the week the way a 7-day sleep would.
        local = now.astimezone(RECAP_ZONE)
        if local.weekday() != RECAP_DAY or local.hour != RECAP_HOUR:
            return

        await self.post_recaps(now)

    @recap.before_loop
    async def before_recap(self) -> None:
        await self.bot.wait_until_ready()

    async def post_recaps(self, now: datetime) -> None:
        since = now - timedelta(days=7)
        configs = await guild_config_db.get_all()

        for config in configs:
            # The loop runs its first tick the moment the cog loads, so a
            # restart inside the recap hour re-enters here. The recap is the
            # only thing that pings; sending it twice is the exact noise it
            # exists to remove.
            if (
                config.last_recap_at is not None
                and now - config.last_recap_at < _MIN_RECAP_GAP
            ):
                _log.info(
                    "Weekly recap: guild %s already received a recap at %s, skipping",
                    config.guild_id,
                    config.last_recap_at,
                )
                continue

            config.last_recap_at = now
            await guild_config_db.upsert(config)

            posts = await job_post_db.get_posted_since(config.guild_id, since)
            if not posts:
                _log.info(
                    "Weekly recap: nothing posted in guild %s this week",
                    config.guild_id,
                )
                continue

            # Once per guild, not per audience: both recaps rank against the
            # same forum, and this is the only API call either of them needs.
            replies = await thread_reply_counts(
                self.bot, config.guild_id, config.forum_channel_id
            )

            grouped: dict[str, list[JobPost]] = {
                INTERN_AUDIENCE: [],
                GRAD_AUDIENCE: [],
            }
            for post in posts:
                grouped[audience_for(post.job_type)].append(post)

            for audience, audience_posts in grouped.items():
                if not audience_posts:
                    continue
                await self._send(config, audience, audience_posts, replies)

    async def _send(
        self,
        config: GuildConfig,
        audience: str,
        posts: list[JobPost],
        replies: dict[int, int],
    ) -> None:
        channel_id = getattr(config, AUDIENCE_CHANNEL_ATTR[audience], None)
        if not channel_id:
            _log.info(
                "Weekly recap: guild %s has no %s recap channel configured, skipping %d posts",
                config.guild_id,
                audience,
                len(posts),
            )
            return

        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(
                channel_id
            )
        except discord.NotFound:
            _log.warning(
                "Weekly recap: channel %s not found for guild %s",
                channel_id,
                config.guild_id,
            )
            return
        except Exception:  # noqa: BLE001
            _log.exception(
                "Weekly recap: failed to fetch channel %s for guild %s",
                channel_id,
                config.guild_id,
            )
            return

        message = build_recap(
            posts,
            audience,
            role_mentions(config, audience),
            config.forum_channel_id,
            replies,
        )

        try:
            await channel.send(
                message,
                # The recap is the only thing that pings, so the mentions in it
                # have to actually resolve.
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            _log.info(
                "Weekly recap: posted %d %s roles to guild %s",
                len(posts),
                audience,
                config.guild_id,
            )
        except Exception:  # noqa: BLE001
            _log.exception(
                "Weekly recap: failed to post %s recap for guild %s",
                audience,
                config.guild_id,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WeeklyRecap(bot))
