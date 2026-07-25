from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import ClassVar

import discord
from discord.ext import commands

from src.backend.mongo.collections.col_jobs import job_col
from src.backend.mongo.triggers import ChangeEvent, ChangeStreamWatcher, Operation
from src.backend.sql.tables import guild_config_db, job_post_db
from src.backend.sql.models import JobPost
from src.core.functions.job_embed import build_job_embed
from src.core.views.job_delete_confirm import DeleteConfirmView

_log = logging.getLogger(__name__)


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
            _log.warning("INSERT event missing full_document for id=%s", event.document_id)
            return

        embed = build_job_embed(job)
        guild_configs = await guild_config_db.get_all()
        if not guild_configs:
            return

        for config in guild_configs:
            try:
                channel = self.bot.get_channel(config.forum_channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(config.forum_channel_id)
            except discord.NotFound:
                _log.warning(
                    "Forum channel %s not found for guild %s",
                    config.forum_channel_id,
                    config.guild_id,
                )
                continue
            except Exception:
                _log.exception(
                    "Failed to fetch forum channel %s for guild %s",
                    config.forum_channel_id,
                    config.guild_id,
                )
                continue

            if not isinstance(channel, discord.ForumChannel):
                _log.warning(
                    "Channel %s for guild %s is not a ForumChannel",
                    config.forum_channel_id,
                    config.guild_id,
                )
                continue

            try:
                thread, _ = await channel.create_thread(
                    name=f"{job.title} | {job.company.name}"[:100],
                    embed=embed,
                    auto_archive_duration=10080,
                )
            except Exception:
                _log.exception(
                    "Failed to create forum thread in channel %s for guild %s",
                    config.forum_channel_id,
                    config.guild_id,
                )
                continue

            post = JobPost(
                job_id=event.document_id,
                guild_id=config.guild_id,
                forum_post_id=thread.id,
                forum_channel_id=channel.id,
                posted_at=datetime.now(tz=timezone.utc),
            )
            await job_post_db.upsert(post)
            _log.info(
                "Created forum thread %s for job %s in guild %s",
                thread.id,
                event.document_id,
                config.guild_id,
            )

    # ------------------------------------------------------------------
    # UPDATE / REPLACE: edit the starter message in each thread
    # ------------------------------------------------------------------

    async def _handle_update(self, event: ChangeEvent) -> None:
        job = event.full_document
        if job is None:
            _log.warning("UPDATE event missing full_document for id=%s", event.document_id)
            return

        posts = await job_post_db.get_by_job_id(event.document_id)
        if not posts:
            # Job was added after this guild configured the watcher — treat as insert
            _log.info(
                "No posts found for job %s on update; treating as insert",
                event.document_id,
            )
            await self._handle_insert(event)
            return

        embed = build_job_embed(job)
        for post in posts:
            try:
                thread = await self.bot.fetch_channel(post.forum_post_id)
                message = await thread.fetch_message(thread.id)
                await message.edit(embed=embed)
            except discord.NotFound:
                _log.warning(
                    "Thread or message not found for post job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )
            except Exception:
                _log.exception(
                    "Failed to update forum thread for job=%s guild=%s",
                    post.job_id,
                    post.guild_id,
                )

    # ------------------------------------------------------------------
    # DELETE: send a role-gated deletion prompt
    # ------------------------------------------------------------------

    async def _handle_delete(self, document_id: str) -> None:
        posts = await job_post_db.get_by_job_id(document_id)
        pending_posts = [p for p in posts if not p.awaiting_deletion]
        if not pending_posts:
            return

        for post in pending_posts:
            try:
                thread = await self.bot.fetch_channel(post.forum_post_id)
            except discord.NotFound:
                _log.warning(
                    "Thread %s not found during delete prompt for job=%s guild=%s",
                    post.forum_post_id,
                    post.job_id,
                    post.guild_id,
                )
                continue
            except Exception:
                _log.exception(
                    "Failed to fetch thread for delete prompt job=%s guild=%s",
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
            except Exception:
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
