from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Final

import discord
from discord.ext import commands, tasks

from src.backend.sql.models import DeadlineReminder, JobPost
from src.backend.sql.tables import job_post_db
from src.config import CLOSE_ARCHIVE_QUIET_DAYS, DEADLINE_CHECK_INTERVAL_MINUTES
from src.core.functions.job_groups import live_posts
from src.core.functions.job_post import (
    CLOSED_PREFIX,
    MAX_THREAD_NAME,
    build_thread_name,
    refresh_apply_buttons,
)

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
        "🚨 Applications for this position close in within **3 days**.",
    ),
    (
        DeadlineReminder.REMINDER_1W,
        7.0,
        "🚨 Applications for this position close in within **1 week**.",
    ),
    (
        DeadlineReminder.REMINDER_2W,
        14.0,
        "🚨 Applications for this position close in within **2 weeks**.",
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

        # Several listings can share a thread when one role is advertised per
        # city, and each closes on its own date. The thread belongs to all of
        # them, so it follows the last one to close.
        siblings = await job_post_db.get_by_forum_post_id(post.forum_post_id)
        others = [p for p in siblings if p.job_id != post.job_id]

        if post.outdated or (post.close_date is not None and post.close_date <= now):
            still_hiring = live_posts(others)
            if still_hiring:
                # This city has closed but the role has not. Drop its button so
                # nobody applies to a dead posting, and leave the thread open
                # for the cities that are still taking applications.
                await self._retire_listing(thread, post, still_hiring)
                return
            await self._on_closed(thread, post)
            return

        assert post.close_date is not None
        days_remaining = (post.close_date - now).total_seconds() / 86400

        # One reminder per thread, not per listing. Three postings of the same
        # role would otherwise send three identical warnings, and a warning
        # about the whole thread closing is only true of the last one to go.
        if any(
            other.close_date is not None
            and post.close_date is not None
            and (other.close_date, other.job_id) > (post.close_date, post.job_id)
            for other in live_posts(others)
        ):
            return

        for i, (reminder, threshold_days, message) in enumerate(_REMINDER_THRESHOLDS):
            lower = _REMINDER_THRESHOLDS[i - 1][1] if i > 0 else 0.0
            if (
                lower < days_remaining <= threshold_days
                and reminder not in post.deadline_reminders_sent
            ):
                await self._send_reminder(thread, post, reminder, message)
                break

    async def _retire_listing(
        self,
        thread: discord.Thread,
        post: JobPost,
        remaining: list[JobPost],
    ) -> None:
        """Take one closed listing off a thread that is still hiring elsewhere.

        Nothing is announced. A city closing is not the role closing, and a
        notice in the thread would read as though it were; the button
        disappearing is the honest signal. The listing is marked closed so the
        deadline check stops picking it up.
        """
        try:
            await refresh_apply_buttons(self.bot, thread, remaining)
        except Exception:  # noqa: BLE001
            _log.exception(
                "Failed to refresh apply buttons on thread %s after job=%s closed",
                thread.id,
                post.job_id,
            )

        await job_post_db.mark_reminder_sent(
            post.job_id, post.guild_id, DeadlineReminder.CLOSED
        )
        _log.info(
            "Listing closed but thread %s kept: %d other listing(s) still open "
            "(job=%s guild=%s)",
            thread.id,
            len(remaining),
            post.job_id,
            post.guild_id,
        )

    async def _has_recent_user_activity(self, thread: discord.Thread) -> bool:
        """Return True if a non-bot message was posted in the last quiet window.

        Only messages from people count. The bot's own reminders and closing
        notice are not a conversation, and treating them as one would keep every
        post open forever.

        On failure this reports activity, leaving the thread open: Discord's
        inactivity timer will archive it anyway, whereas archiving a thread
        somebody is talking in cannot be undone by waiting.
        """
        cutoff = datetime.now(tz=timezone.utc) - timedelta(
            days=CLOSE_ARCHIVE_QUIET_DAYS
        )
        try:
            async for message in thread.history(after=cutoff, limit=None):
                if message.author != self.bot.user:
                    return True
            return False
        except Exception:  # noqa: BLE001
            _log.exception(
                "Failed to read history for thread %s; leaving it open", thread.id
            )
            return True

    async def _on_closed(self, thread: discord.Thread, post: JobPost) -> None:
        try:
            closed_name = CLOSED_PREFIX + build_thread_name(
                post.company_name, post.title
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

            # Checked before the closing notice is sent, so the notice cannot
            # be mistaken for activity even if the author filter ever changes.
            has_activity = await self._has_recent_user_activity(thread)

            await thread.edit(
                name=closed_name[:MAX_THREAD_NAME], applied_tags=updated_tags
            )
            await thread.send("Applications for this position are now closed.")

            # A closed post is not a finished one. People come back to say they
            # got an interview or an offer, and archiving hides it from the
            # forum view, so a post with a live conversation stays open and is
            # left to Discord's inactivity timer once that conversation ends.
            if has_activity:
                _log.info(
                    "Closed but left open (recent discussion): job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )
            else:
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
