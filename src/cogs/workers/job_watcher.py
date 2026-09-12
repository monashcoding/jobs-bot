from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import ClassVar, Final

import discord
from discord.ext import commands

from src.backend.mongo.collections.col_jobs import JobDocument, job_col
from src.backend.mongo.triggers import ChangeEvent, ChangeStreamWatcher, Operation
from src.backend.sql.models import GuildConfig, JobPost
from src.backend.sql.tables import guild_config_db, job_post_db
from src.core.functions.job_eligibility import (
    is_board_eligible,
    is_open_for_applications,
    is_post_open,
)
from src.core.functions.job_embed import build_job_embed
from src.core.functions.job_groups import (
    group_key,
    live_posts,
    primary_post,
    widen_to_thread,
)
from src.core.functions.job_post import (
    build_job_post,
    post_job_to_guild,
    refresh_apply_buttons,
)
from src.core.functions.job_tags import ensure_tags, resync_tags
from src.core.views.job_delete_confirm import DeleteConfirmView

_log: Final[logging.Logger] = logging.getLogger(__name__)


class JobWatcher(ChangeStreamWatcher):
    """Watches the active_jobs MongoDB collection and mirrors changes to Discord forum threads."""

    collection = job_col
    operations: ClassVar[list[Operation]] = [
        Operation.INSERT,
        Operation.UPDATE,
        Operation.REPLACE,
        Operation.DELETE,
    ]

    async def cog_load(self) -> None:
        await super().cog_load()
        await self._reregister_pending_views()

    async def _reregister_pending_views(self) -> None:
        """Re-register persistent DeleteConfirmViews for posts awaiting deletion."""
        pending = await job_post_db.get_pending_deletions()
        _log.info("Re-registering %d pending deletion view(s)", len(pending))
        for post in pending:
            if post.deletion_message_id:
                view = DeleteConfirmView(post.job_id, post.guild_id)
                self.bot.add_view(view, message_id=post.deletion_message_id)
                _log.debug(
                    "Re-registered deletion view for job=%s guild=%s message=%s",
                    post.job_id,
                    post.guild_id,
                    post.deletion_message_id,
                )

    async def on_change(self, event: ChangeEvent) -> None:
        if event.operation is Operation.INSERT:
            await self._handle_insert(event)
        elif event.operation in (Operation.UPDATE, Operation.REPLACE):
            await self._handle_update(event)

    async def on_delete(self, document_id: str) -> None:
        await self._handle_delete(document_id)

    # ------------------------------------------------------------------
    # INSERT: create a forum thread per guild
    # ------------------------------------------------------------------

    async def _handle_insert(self, event: ChangeEvent) -> None:
        job = event.full_document
        if job is None:
            _log.warning(
                "INSERT event missing full_document for id=%s", event.document_id
            )
            return

        _log.info("INSERT job_id=%s title=%r", event.document_id, job.title)

        # The collection holds every job scraped, not only the ones that belong
        # on the board. Without this the watcher creates a thread per document
        # and runs straight into Discord's 1000 active-thread forum cap.
        #
        # This is also the choke point for the update path below, which routes
        # an update for a job it has no thread for back through here.
        if not is_board_eligible(job):
            _log.info(
                "Skipping ineligible job_id=%s title=%r", event.document_id, job.title
            )
            return

        guild_configs = await guild_config_db.get_all()
        _log.debug(
            "Found %d guild config(s) for INSERT job_id=%s",
            len(guild_configs),
            event.document_id,
        )
        if not guild_configs:
            _log.warning(
                "No guild configs found; job_id=%s will not be posted",
                event.document_id,
            )
            return
        for config in guild_configs:
            if await self._attach_to_existing_thread(job, config):
                continue
            await post_job_to_guild(self.bot, job, config)

    async def _attach_to_existing_thread(
        self,
        job: JobDocument,
        config: GuildConfig,
    ) -> bool:
        """Add *job* to the thread for its role, if one is already up.

        An employer opening the same role in a second city produces a second
        listing days after the first, which would otherwise become a second
        thread for a role the board already carries. It joins the existing
        thread instead, as another apply button and another row against the same
        forum_post_id.

        Only threads that are still hiring are joined. Once every listing on a
        thread has closed it is a record of a finished role, and a new opening
        deserves its own thread rather than reviving that one.
        """
        # A listing that cannot be applied to earns no button. post_job_group
        # applies the same gate when it creates a thread; this is the other way
        # a listing gets onto one.
        if not is_open_for_applications(job):
            return False

        posts = await job_post_db.get_by_guild(config.guild_id)
        siblings = [
            post
            for post in posts
            if group_key(post.company_name, post.title)
            == group_key(job.company.name, job.title)
        ]
        open_siblings = live_posts(siblings)
        if not open_siblings:
            return False

        thread_id = primary_post(open_siblings).forum_post_id
        on_thread = [post for post in siblings if post.forum_post_id == thread_id]

        try:
            thread = await self.bot.fetch_channel(thread_id)
        except Exception:  # noqa: BLE001
            _log.exception(
                "Failed to fetch thread %s to attach job=%s; posting separately",
                thread_id,
                job.id,
            )
            return False

        await job_post_db.upsert(
            build_job_post(job, config, thread_id, thread.parent_id)
        )

        listings = [
            *on_thread,
            build_job_post(job, config, thread_id, thread.parent_id),
        ]
        try:
            await refresh_apply_buttons(self.bot, thread, live_posts(listings))
            await self._resync_tags(thread, job, listings)
        except Exception:  # noqa: BLE001
            _log.exception(
                "Attached job=%s to thread %s but failed to refresh it",
                job.id,
                thread_id,
            )

        _log.info(
            "Attached job=%s (%s) to existing thread %s in guild %s",
            job.id,
            ", ".join(job.locations) or "no location",
            thread_id,
            config.guild_id,
        )
        return True

    # ------------------------------------------------------------------
    # UPDATE / REPLACE: edit the starter message in each thread
    # ------------------------------------------------------------------

    async def _handle_update(self, event: ChangeEvent) -> None:
        job = event.full_document
        if job is None:
            _log.warning(
                "UPDATE event missing full_document for id=%s", event.document_id
            )
            return

        _log.info(
            "%s job_id=%s title=%r",
            event.operation.value.upper(),
            event.document_id,
            job.title,
        )
        posts = await job_post_db.get_by_job_id(event.document_id)
        if not posts:
            # Job was added after this guild configured the watcher; treat as insert
            _log.info(
                "No posts found for job %s on update; treating as insert",
                event.document_id,
            )
            await self._handle_insert(event)
            return

        embed = build_job_embed(job)
        for post in posts:
            await job_post_db.sync_fields(
                post.job_id,
                post.guild_id,
                outdated=job.outdated,
                close_date=job.close_date,
                title=job.title,
                job_type=job.type,
                # Kept in sync rather than frozen at post time, so a re-run of
                # the scraper's tier backfill reaches threads that already
                # exist. Without this the recap would order already-posted jobs
                # by whatever the tier was on the day they were posted.
                company_tier=job.company_tier,
                one_liner=job.one_liner,
                is_sponsored=job.is_sponsored,
                wfh_status=job.wfh_status,
                locations=job.locations,
                working_rights=job.working_rights,
            )
            try:
                thread = await self.bot.fetch_channel(post.forum_post_id)
                siblings = await job_post_db.get_by_forum_post_id(post.forum_post_id)

                # The thread shows one role. Where several listings share it,
                # the embed is the primary's and the buttons are everyone's, so
                # an update to a sibling changes the links without rewriting the
                # thread around whichever city happened to be edited.
                message = await thread.fetch_message(thread.id)
                if primary_post(siblings).job_id == post.job_id:
                    await message.edit(embed=embed)

                if len(siblings) > 1:
                    await refresh_apply_buttons(self.bot, thread, live_posts(siblings))

                await self._resync_tags(thread, job, siblings)
                _log.info(
                    "Updated embed for job=%s guild=%s thread=%s",
                    post.job_id,
                    post.guild_id,
                    post.forum_post_id,
                )
            except discord.NotFound:
                _log.warning(
                    "Thread or message not found for post job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )
            except Exception:  # noqa: BLE001
                _log.exception(
                    "Failed to update forum thread for job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )

    async def _resync_tags(
        self,
        thread: discord.Thread,
        job: JobDocument,
        siblings: Sequence[JobPost] | None = None,
    ) -> None:
        """Bring *thread*'s tags back in line with the job document behind it.

        Tags are set once at post time and never revisited, so every later
        revision by the scraper -- a second city, re-parsed working rights, a
        deadline that moves into the next year -- leaves the thread advertising
        the job as it was the day it went up.

        This is meant to be invisible on the board. Editing tags posts no
        message and does not bump the thread, so a correction lands silently,
        with two things kept off the table:

        - Archived threads are left alone. Editing one unarchives it, which
          would drag a long-dead posting back to the top of the forum -- the
          most visible thing this could possibly do, for a thread nobody is
          reading anyway. /fix-tags exists for that case and is asked for.
        - The Open/Closed tag is carried across untouched (see resync_tags),
          so a closed posting is not quietly reopened by a scraper edit.
        """
        if thread.archived:
            return

        parent = thread.parent
        if parent is None:
            parent = await self.bot.fetch_channel(thread.parent_id)
        if not isinstance(parent, discord.ForumChannel):
            return

        # Tags describe the thread, so a role split across cities is tagged
        # with all of them rather than with whichever listing was edited.
        widened = widen_to_thread(job, siblings or [])

        tag_map = await ensure_tags(parent, widened)
        new_tags = resync_tags(widened, tag_map, list(thread.applied_tags))
        if new_tags is None:
            return

        await thread.edit(applied_tags=new_tags)
        _log.info(
            "Resynced tags for thread=%s: %s",
            thread.id,
            ", ".join(t.name for t in new_tags),
        )

    # ------------------------------------------------------------------
    # DELETE: keep open roles, auto-delete bot-only threads, otherwise prompt
    # ------------------------------------------------------------------

    async def _detach_listing(self, post: JobPost, remaining: list[JobPost]) -> None:
        """Drop one listing from a thread that other listings still hold open.

        The row goes and the button with it, silently: a city's posting being
        withdrawn is not news about the role, and a thread that keeps a dead
        link is worse than one that quietly stops offering it.
        """
        await job_post_db.delete(post.job_id, post.guild_id)

        try:
            thread = await self.bot.fetch_channel(post.forum_post_id)
            await refresh_apply_buttons(self.bot, thread, remaining)
        except Exception:  # noqa: BLE001
            _log.exception(
                "Removed job=%s from thread %s but failed to refresh its buttons",
                post.job_id,
                post.forum_post_id,
            )

        _log.info(
            "Removed job=%s from thread %s; %d listing(s) still open",
            post.job_id,
            post.forum_post_id,
            len(remaining),
        )

    async def _has_user_messages(self, thread: discord.Thread) -> bool:
        """Return True if the thread has any message not authored by the bot."""
        async for message in thread.history(limit=None):
            if message.author != self.bot.user:
                return True
        return False

    async def _handle_delete(self, document_id: str) -> None:
        _log.info("DELETE job_id=%s", document_id)
        posts = await job_post_db.get_by_job_id(document_id)
        pending_posts = [p for p in posts if not p.awaiting_deletion]
        already_pending = len(posts) - len(pending_posts)
        if already_pending:
            _log.debug(
                "DELETE job_id=%s: %d post(s) already awaiting deletion, skipping",
                document_id,
                already_pending,
            )
        if not pending_posts:
            _log.info("DELETE job_id=%s: no actionable posts found", document_id)
            return
        _log.info(
            "DELETE job_id=%s: sending prompt to %d guild(s)",
            document_id,
            len(pending_posts),
        )

        for post in pending_posts:
            # A thread showing several cities loses only the listing that went
            # away. The thread belongs to the others, and deleting it -- or
            # asking whether to -- over one city's posting disappearing would
            # take a role people can still apply to off the board.
            siblings = await job_post_db.get_by_forum_post_id(post.forum_post_id)
            remaining = live_posts([p for p in siblings if p.job_id != post.job_id])
            if remaining:
                await self._detach_listing(post, remaining)
                continue

            # Checked before the thread is fetched: an open role is kept
            # whatever is in its thread, so there is nothing to look at.
            if is_post_open(post):
                _log.info(
                    "DELETE job_id=%s guild=%s: deadline has not passed, keeping "
                    "the thread. It will close and archive on its own deadline.",
                    post.job_id,
                    post.guild_id,
                )
                continue

            try:
                thread = await self.bot.fetch_channel(post.forum_post_id)
            except discord.NotFound:
                _log.warning(
                    "Thread %s not found during delete for job=%s guild=%s",
                    post.forum_post_id,
                    post.job_id,
                    post.guild_id,
                )
                continue
            except Exception:  # noqa: BLE001
                _log.exception(
                    "Failed to fetch thread for delete job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )
                continue

            try:
                has_user_msgs = await self._has_user_messages(thread)
            except Exception:  # noqa: BLE001
                _log.exception(
                    "Failed to scan messages for job=%s guild=%s; falling back to prompt",
                    post.job_id,
                    post.guild_id,
                )
                has_user_msgs = True

            if not has_user_msgs:
                # No user engagement — silently delete the thread and DB record.
                try:
                    await thread.delete()
                except Exception:  # noqa: BLE001
                    _log.exception(
                        "Failed to auto-delete thread for job=%s guild=%s",
                        post.job_id,
                        post.guild_id,
                    )
                await job_post_db.delete(post.job_id, post.guild_id)
                _log.info(
                    "Auto-deleted bot-only thread for job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )
                continue

            view = DeleteConfirmView(post.job_id, post.guild_id)
            try:
                prompt_msg = await thread.send(
                    "This job has been removed from the source. "
                    "Would you like to delete this post?",
                    view=view,
                )
            except Exception:  # noqa: BLE001
                _log.exception(
                    "Failed to send deletion prompt for job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )
                continue

            await job_post_db.set_awaiting_deletion(
                post.job_id,
                post.guild_id,
                deletion_message_id=prompt_msg.id,
            )
            _log.info(
                "Sent deletion prompt %s for job=%s guild=%s",
                prompt_msg.id,
                post.job_id,
                post.guild_id,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JobWatcher(bot))
