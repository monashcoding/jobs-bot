from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Final
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from src.backend.sql.models import GuildConfig, JobPost
from src.backend.sql.tables import guild_config_db, job_post_db
from src.config import RECAP_DAY, RECAP_HOUR, RECAP_TIMEZONE
from src.core.functions.company_rank import rank_for
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
_MAX_LISTED: Final[int] = 8

# Discord rejects messages over 2000 characters. Eight entries do not come close
# even with long titles, so this is a backstop against a pathological title
# rather than the thing that shapes the message.
_MAX_MESSAGE_LENGTH: Final[int] = 1900

# Room kept free so the "and N more" line always fits, whatever the entries did
# to the budget. A dropped count is worse than a dropped entry: it is the only
# thing telling the reader the list is partial.
_OVERFLOW_RESERVE: Final[int] = 120

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


def recap_order(posts: list[JobPost]) -> list[JobPost]:
    """Order postings for the recap, most recognisable employer first.

    The board's company list is a gate, so every posting here is from a company
    worth posting; that is exactly why it cannot order them. Ranking by
    prominence puts the names people open the message for at the top, which
    matters once only the first few are shown.

    Postings from equally prominent employers keep the order the query returned
    them in, oldest first, so a week's recap reads consistently.
    """
    return sorted(
        posts, key=lambda post: rank_for(post.company_tier, post.company_name)
    )


def build_recap(
    posts: list[JobPost], audience: str, mentions: str, forum_channel_id: int
) -> str:
    """Render one audience's recap message."""
    label = AUDIENCE_LABEL[audience]
    heading = f"{mentions} **{len(posts)} new {label} role{'s' if len(posts) != 1 else ''} this week**".strip()

    lines = [heading, ""]
    length = len(heading) + 1
    listed = 0

    for post in recap_order(posts)[:_MAX_LISTED]:
        link = f"https://discord.com/channels/{post.guild_id}/{post.forum_post_id}"
        line = f"\u2022 [{post.title}]({link})"
        if length + len(line) + 1 > _MAX_MESSAGE_LENGTH - _OVERFLOW_RESERVE:
            break
        lines.append(line)
        length += len(line) + 1
        listed += 1

    # Always a real channel link: the line exists to send people somewhere, and
    # naming the board without linking it makes them go and find it.
    if listed < len(posts):
        lines.append(f"\u2026and {len(posts) - listed} more in <#{forum_channel_id}>.")

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

            grouped: dict[str, list[JobPost]] = {
                INTERN_AUDIENCE: [],
                GRAD_AUDIENCE: [],
            }
            for post in posts:
                grouped[audience_for(post.job_type)].append(post)

            for audience, audience_posts in grouped.items():
                if not audience_posts:
                    continue
                await self._send(config, audience, audience_posts)

    async def _send(
        self, config: GuildConfig, audience: str, posts: list[JobPost]
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
            posts, audience, role_mentions(config, audience), config.forum_channel_id
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
