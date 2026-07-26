from __future__ import annotations

import logging
from typing import ClassVar, Final

import discord
from discord.ext import commands

from src.backend.mongo.collections.col_jobs import job_col
from src.backend.mongo.triggers import ChangeEvent, ChangeStreamWatcher, Operation
from src.backend.sql.tables import guild_config_db, job_post_db
from src.core.functions.job_embed import build_job_embed
from src.core.functions.job_post import post_job_to_guild
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
        guild_configs = await guild_config_db.get_all()
        _log.debug("Found %d guild config(s) for INSERT job_id=%s", len(guild_configs), event.document_id)
        if not guild_configs:
            _log.warning("No guild configs found; job_id=%s will not be posted", event.document_id)
            return
        for config in guild_configs:
            await post_job_to_guild(self.bot, job, config)

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

        _log.info("%s job_id=%s title=%r", event.operation.value.upper(), event.document_id, job.title)
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
            try:
                thread = await self.bot.fetch_channel(post.forum_post_id)
                message = await thread.fetch_message(thread.id)
                await message.edit(embed=embed)
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

    # ------------------------------------------------------------------
    # DELETE: send a role-gated deletion prompt
    # ------------------------------------------------------------------

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
        _log.info("DELETE job_id=%s: sending prompt to %d guild(s)", document_id, len(pending_posts))

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
            except Exception:  # noqa: BLE001
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
