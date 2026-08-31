from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Final

import discord
from discord.ext import commands, tasks

from src.backend.sql.models import GuildConfig, JobPost
from src.backend.sql.tables import guild_config_db, job_post_db
from src.config import RECAP_DAY, RECAP_HOUR_UTC
from src.core.functions.job_post import (
    AUDIENCE_CHANNEL_ATTR,
    AUDIENCE_LABEL,
    AUDIENCE_ROLE_ATTRS,
    GRAD_AUDIENCE,
    INTERN_AUDIENCE,
    TYPE_TO_AUDIENCE,
)

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Discord rejects messages over 2000 characters. A busy week can list more jobs
# than that, so the list is truncated with a count of what was left out.
_MAX_MESSAGE_LENGTH: Final[int] = 1900
_MAX_LISTED: Final[int] = 25


def audience_for(job_type: str | None) -> str:
    """Return the recap audience a posting belongs to.

    An unknown or missing type falls to the graduate recap rather than being
    dropped: interns are the narrower audience, so a misfiled graduate posting
    is a smaller mistake than a silently missing one.
    """
    if job_type is None:
        return GRAD_AUDIENCE
    return TYPE_TO_AUDIENCE.get(job_type, GRAD_AUDIENCE)


def build_recap(posts: list[JobPost], audience: str, mentions: str) -> str:
    """Render one audience's recap message."""
    label = AUDIENCE_LABEL[audience]
    heading = f"{mentions} **{len(posts)} new {label} role{'s' if len(posts) != 1 else ''} this week**".strip()

    lines = [heading, ""]
    for post in posts[:_MAX_LISTED]:
        link = f"https://discord.com/channels/{post.guild_id}/{post.forum_post_id}"
        lines.append(f"• [{post.title}]({link})")

    if len(posts) > _MAX_LISTED:
        lines.append(f"…and {len(posts) - _MAX_LISTED} more in the job board.")

    message = "\n".join(lines)
    if len(message) > _MAX_MESSAGE_LENGTH:
        message = message[:_MAX_MESSAGE_LENGTH].rsplit("\n", 1)[0]
        message += "\n…see the job board for the rest."
    return message


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
        # The loop ticks hourly and fires on the configured day and hour, so a
        # restart cannot skip the week the way a 7-day sleep would.
        if now.weekday() != RECAP_DAY or now.hour != RECAP_HOUR_UTC:
            return

        await self.post_recaps(now)

    @recap.before_loop
    async def before_recap(self) -> None:
        await self.bot.wait_until_ready()

    async def post_recaps(self, now: datetime) -> None:
        since = now - timedelta(days=7)
        configs = await guild_config_db.get_all()

        for config in configs:
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

        message = build_recap(posts, audience, role_mentions(config, audience))

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
