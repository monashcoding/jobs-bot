from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Final

import discord
from discord.ext import commands, tasks

from src.backend.sql.models import DeadlineReminder, JobPost
from src.backend.sql.tables import job_post_db
from src.config import DEADLINE_CHECK_INTERVAL_MINUTES
from src.core.functions.job_post import build_thread_name

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Ordered most-urgent-first. Only the first applicable unsent reminder fires per cycle.
_REMINDER_THRESHOLDS: Final[list[tuple[DeadlineReminder, float, str]]] = [
    (
        DeadlineReminder.REMINDER_1D,
        1.0,
        "🚨 Applications for this position close **tomorrow**.",
    ),
    (
        DeadlineReminder.REMINDER_3D,
        3.0,
        "🚨 Applications for this position close in **3 days**.",
    ),
    (
        DeadlineReminder.REMINDER_1W,
        7.0,
        "🚨 Applications for this position close in **1 week**.",
    ),
    (
        DeadlineReminder.REMINDER_2W,
        14.0,
        "🚨 Applications for this position close in **2 weeks**.",
    ),
]


class DeadlineWatcher(commands.Cog):
    """Periodically checks job post close dates and sends reminders or closure notices."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self.check_deadlines.start()

    def cog_unload(self) -> None:
        self.check_deadlines.cancel()

    @tasks.loop(minutes=DEADLINE_CHECK_INTERVAL_MINUTES)
    async def check_deadlines(self) -> None:
        await self._run_check()

    async def _run_check(self) -> int:
        """Run one deadline check pass. Returns the number of posts checked.

        Returns -1 if another check is already in progress.
        """
        if self._lock.locked():
            _log.info("Deadline check skipped: another check is already in progress")
            return -1
        async with self._lock:
            posts = await job_post_db.get_active_with_close_date()
            _log.debug("Deadline check: %d post(s) with active close dates", len(posts))
            now = datetime.now(tz=timezone.utc)
            for post in posts:
                await self._process_post(post, now)
            return len(posts)

    @check_deadlines.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()

    async def _process_post(self, post: JobPost, now: datetime) -> None:
        try:
            thread = await self.bot.fetch_channel(post.forum_post_id)
        except discord.NotFound:
            _log.warning(
                "Thread %s not found for deadline check job=%s guild=%s",
                post.forum_post_id,
                post.job_id,
                post.guild_id,
            )
            return
        except Exception:  # noqa: BLE001
            _log.exception(
                "Failed to fetch thread %s for job=%s guild=%s",
                post.forum_post_id,
                post.job_id,
                post.guild_id,
            )
            return

        if post.outdated:
            await self._on_closed(thread, post)
            return

        assert post.close_date is not None
        days_remaining = (post.close_date - now).total_seconds() / 86400

        if days_remaining <= 0:
            await self._on_closed(thread, post)
            return

        for i, (reminder, threshold_days, message) in enumerate(_REMINDER_THRESHOLDS):
            lower = _REMINDER_THRESHOLDS[i - 1][1] if i > 0 else 0.0
            if (
                lower < days_remaining <= threshold_days
                and reminder not in post.deadline_reminders_sent
            ):
                await self._send_reminder(thread, post, reminder, message)
                break

    async def _on_closed(self, thread: discord.Thread, post: JobPost) -> None:
        try:
            year_dt = post.close_date or post.job_updated_at or post.job_created_at
            closed_name = "❌ " + build_thread_name(
                post.title, post.company_name, year_dt.year
            )

            parent = thread.parent
            if parent is None:
                try:
                    parent = await self.bot.fetch_channel(thread.parent_id)
                except Exception:  # noqa: BLE001
                    parent = None

            updated_tags = [t for t in thread.applied_tags if t.name != "Open"]
            if parent is not None:
                closed_tag = discord.utils.get(parent.available_tags, name="Closed")
                if closed_tag and closed_tag not in updated_tags:
                    updated_tags.append(closed_tag)

            await thread.edit(name=closed_name[:100], applied_tags=updated_tags)
            await thread.send("Applications for this position are now closed.")
            await thread.edit(archived=True)
            await job_post_db.mark_reminder_sent(
                post.job_id, post.guild_id, DeadlineReminder.CLOSED
            )
            _log.info("Marked closed: job=%s guild=%s", post.job_id, post.guild_id)
        except Exception:  # noqa: BLE001
            _log.exception(
                "Failed to process closure for job=%s guild=%s",
                post.job_id,
                post.guild_id,
            )

    async def _send_reminder(
        self,
        thread: discord.Thread,
        post: JobPost,
        reminder: DeadlineReminder,
        message: str,
    ) -> None:
        try:
            await thread.send(message)
            await job_post_db.mark_reminder_sent(post.job_id, post.guild_id, reminder)
            _log.info(
                "Sent %s reminder for job=%s guild=%s",
                reminder.value,
                post.job_id,
                post.guild_id,
            )
        except Exception:  # noqa: BLE001
            _log.exception(
                "Failed to send %s reminder for job=%s guild=%s",
                reminder.value,
                post.job_id,
                post.guild_id,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeadlineWatcher(bot))
