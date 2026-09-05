from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Final

import discord
from discord import app_commands
from discord.ext import commands

from src.backend.mongo.collections.col_jobs import job_col
from src.backend.sql.models import DeadlineReminder, GuildConfig
from src.backend.sql.tables import guild_config_db, job_post_db
from src.core.checks import is_admin, is_team_member
from src.core.functions.command_mention import command_mention
from src.core.functions.forum_threads import fetch_all_forum_threads
from src.core.functions.job_diagnostics import collect_board_diagnostics
from src.core.functions.job_eligibility import fetch_board_eligible_ids
from src.core.functions.job_post import (
    AUDIENCE_CHANNEL_ATTR,
    SyncResult,
    sync_jobs,
)
from src.core.functions.job_tags import apply_tag_limit
from src.core.views.rebuild_confirm import CONFIRM_PHRASE, RebuildConfirmView

_log: Final[logging.Logger] = logging.getLogger(__name__)


class ConfigGroup(app_commands.Group, name="config"):
    """Subcommands for configuring the jobs integration."""

    @app_commands.command(name="set-forum-channel")
    @app_commands.describe(channel="The forum channel where job posts will be created")
    # Team role: moving the board to a different forum is board operation, not
    # server configuration. On a server with no config yet this still needs an
    # administrator, because is_team_member falls back to one when there is no
    # team role to check -- the bootstrap works, the refusal message just talks
    # about the team role rather than saying administrator outright.
    @is_team_member()
    async def set_forum_channel(
        self,
        interaction: discord.Interaction,
        # AppCommandChannel, not ForumChannel: the ForumChannel annotation makes
        # discord.py resolve the picked channel out of the guild cache, and
        # AppCommandChannel.resolve() returns None when the guild is not cached
        # -- which fails the whole command with an opaque TransformerError
        # before any of this runs. This form reads the channel straight from the
        # interaction payload, so configuring a server does not depend on the
        # bot having warmed its cache first.
        channel: app_commands.AppCommandChannel,
    ) -> None:
        """Set the forum channel for job posts in this guild."""
        # Checked here because the payload form accepts any channel type; the
        # ForumChannel annotation used to let Discord's own picker do it.
        if channel.type not in (discord.ChannelType.forum, discord.ChannelType.media):
            await interaction.response.send_message(
                f"{channel.mention} is not a forum channel. Job posts are created "
                "as forum threads, so this has to be a forum.",
                ephemeral=True,
            )
            return

        existing = await guild_config_db.get(interaction.guild_id)
        if existing:
            existing.forum_channel_id = channel.id
            config = existing
        else:
            config = GuildConfig(
                guild_id=interaction.guild_id, forum_channel_id=channel.id
            )
        await guild_config_db.upsert(config)
        _log.info("Guild %s set forum channel to %s", interaction.guild_id, channel.id)
        await interaction.response.send_message(
            f"Job posts will be created in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="set-team-role")
    @app_commands.describe(role="The role that can manage (delete/keep) job posts")
    # Administrator, and the one command that genuinely must be. This is what
    # grants team membership, so gating it on team membership is circular:
    # nobody could grant themselves the role, and the refusal pointed at a role
    # that nothing had created yet.
    @is_admin()
    async def set_team_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        """Set the team role that can manage job post deletions."""
        existing = await guild_config_db.get(interaction.guild_id)
        if existing is None:
            await interaction.response.send_message(
                f"Please set a forum channel first with {command_mention(interaction.client, 'jobs', 'config', 'set-forum-channel')}.",
                ephemeral=True,
            )
            return
        existing.team_role_id = role.id
        await guild_config_db.upsert(existing)
        _log.info("Guild %s set team role to %s", interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"{role.mention} can now manage job post deletions.", ephemeral=True
        )

    @app_commands.command(name="set-recap-channel")
    @app_commands.describe(
        audience="Which recap this channel receives",
        channel="The channel the weekly recap is posted to",
    )
    @app_commands.choices(
        audience=[
            app_commands.Choice(name="Internships", value="intern"),
            app_commands.Choice(name="Graduate/Professional", value="grad"),
        ]
    )
    @is_team_member()
    async def set_recap_channel(
        self,
        interaction: discord.Interaction,
        audience: app_commands.Choice[str],
        # Read from the payload rather than the cache, for the same reason as
        # set-forum-channel above.
        channel: app_commands.AppCommandChannel,
    ) -> None:
        """Set where an audience's weekly recap is posted.

        Job posts no longer ping on creation; the weekly recap is what does.
        An audience with no channel set simply gets no recap.
        """
        if channel.type not in (discord.ChannelType.text, discord.ChannelType.news):
            await interaction.response.send_message(
                f"{channel.mention} is not a text channel. The recap is a message, "
                "so it needs somewhere to post one.",
                ephemeral=True,
            )
            return

        existing = await guild_config_db.get(interaction.guild_id)
        if existing is None:
            await interaction.response.send_message(
                f"Please set a forum channel first with {command_mention(interaction.client, 'jobs', 'config', 'set-forum-channel')}.",
                ephemeral=True,
            )
            return

        setattr(existing, AUDIENCE_CHANNEL_ATTR[audience.value], channel.id)
        await guild_config_db.upsert(existing)
        _log.info(
            "Guild %s set %s recap channel to %s",
            interaction.guild_id,
            audience.value,
            channel.id,
        )
        await interaction.response.send_message(
            f"The weekly {audience.name.lower()} recap will be posted in {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="set-role")
    @app_commands.describe(
        job_type="The job type to set the notification role for",
        role="The role to ping when a new post of this type is created",
    )
    @app_commands.choices(
        job_type=[
            app_commands.Choice(name="Intern/Student", value="intern"),
            app_commands.Choice(name="Graduate", value="grad"),
            app_commands.Choice(name="Professional", value="professional"),
        ]
    )
    # Team role: which role hears about which kind of posting is part of running
    # the board, and the people running it should not need an admin to adjust it.
    @is_team_member()
    async def set_role(
        self,
        interaction: discord.Interaction,
        job_type: app_commands.Choice[str],
        role: discord.Role,
    ) -> None:
        """Set the notification role mentioned in the weekly recap for a given job type."""
        existing = await guild_config_db.get(interaction.guild_id)
        if existing is None:
            await interaction.response.send_message(
                f"Please set a forum channel first with {command_mention(interaction.client, 'jobs', 'config', 'set-forum-channel')}.",
                ephemeral=True,
            )
            return
        setattr(existing, f"{job_type.value}_role_id", role.id)
        await guild_config_db.upsert(existing)
        _log.info(
            "Guild %s set %s notification role to %s",
            interaction.guild_id,
            job_type.value,
            role.id,
        )
        await interaction.response.send_message(
            f"{role.mention} will be pinged for **{job_type.name}** posts.",
            ephemeral=True,
        )

    @app_commands.command(name="view")
    @is_team_member()
    async def view_config(self, interaction: discord.Interaction) -> None:
        """Display the current jobs configuration for this guild."""
        config = await guild_config_db.get(interaction.guild_id)
        if config is None:
            await interaction.response.send_message(
                f"No configuration found. Use {command_mention(interaction.client, 'jobs', 'config', 'set-forum-channel')} to get started.",
                ephemeral=True,
            )
            return

        forum = interaction.guild.get_channel(config.forum_channel_id)
        forum_mention = (
            forum.mention if forum else f"<#{config.forum_channel_id}> (not found)"
        )

        role_mention = "Not set"
        if config.team_role_id:
            role = interaction.guild.get_role(config.team_role_id)
            role_mention = (
                role.mention if role else f"<@&{config.team_role_id}> (not found)"
            )

        def role_mention_or(role_id: int | None) -> str:
            if not role_id:
                return "Not set"
            r = interaction.guild.get_role(role_id)
            return r.mention if r else f"<@&{role_id}> (not found)"

        embed = discord.Embed(
            title="Jobs Configuration", colour=discord.Colour.blurple()
        )
        embed.add_field(name="Forum Channel", value=forum_mention, inline=False)
        embed.add_field(name="Team Role", value=role_mention, inline=False)
        embed.add_field(
            name="Notification Roles",
            value=(
                f"📚 Intern/Student: {role_mention_or(config.intern_role_id)}\n"
                f"🎓 Graduate: {role_mention_or(config.grad_role_id)}\n"
                f"💼 Professional: {role_mention_or(config.professional_role_id)}"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class JobsGroup(app_commands.Group, name="jobs"):
    """Job board configuration commands."""

    def __init__(self) -> None:
        super().__init__()
        self.add_command(ConfigGroup())

    @app_commands.command(name="sync")
    @is_team_member()
    async def sync(self, interaction: discord.Interaction) -> None:
        """Reconcile all active jobs from MongoDB against Discord forum posts."""
        await interaction.response.defer()
        _log.info("Guild %s triggered manual sync", interaction.guild_id)

        webhook_msg = await interaction.followup.send("Syncing jobs...", wait=True)
        msg = await interaction.channel.fetch_message(webhook_msg.id)

        last_edit = time.monotonic()

        async def on_progress(result: SyncResult) -> None:
            nonlocal last_edit
            now = time.monotonic()
            if now - last_edit >= 10:
                await msg.edit(
                    content=f"Syncing jobs... **{result.posted}** posted, **{result.skipped}** skipped"
                )
                last_edit = now

        result = await sync_jobs(interaction.client, on_progress=on_progress)
        if result.aborted:
            await msg.edit(
                content=(
                    "Sync aborted: more board-eligible jobs than the safety limit allows. "
                    "This usually means the scraper is not writing `board_eligible` correctly. "
                    "Nothing was posted; check the bot logs."
                )
            )
            return
        await msg.edit(
            content=f"Sync complete: **{result.posted}** posted, **{result.skipped}** already existed."
        )

    @app_commands.command(name="debug")
    @is_team_member()
    async def debug(self, interaction: discord.Interaction) -> None:
        """Show full debug info for the job post in the current thread."""
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "This command must be used inside a job post thread.", ephemeral=True
            )
            return

        posts = await job_post_db.get_by_forum_post_id(interaction.channel.id)
        if not posts:
            await interaction.response.send_message(
                "No job post record found for this thread.", ephemeral=True
            )
            return

        post = posts[0]
        lines = [
            f"**job_id**: `{post.job_id}`",
            f"**guild_id**: `{post.guild_id}`",
            f"**forum_post_id**: `{post.forum_post_id}`",
            f"**forum_channel_id**: `{post.forum_channel_id}`",
            f"**posted_at**: {discord.utils.format_dt(post.posted_at)}",
            f"**title**: {post.title}",
            f"**company**: {post.company_name}",
            f"**job_type**: {post.job_type}",
            f"**close_date**: {discord.utils.format_dt(post.close_date) if post.close_date else 'N/A'}",
            f"**awaiting_deletion**: {post.awaiting_deletion}",
            f"**reminders_sent**: {post.deadline_reminders_sent or 'none'}",
            f"**is_sponsored**: {post.is_sponsored}",
            f"**source**: {post.source}",
            f"**wfh_status**: {post.wfh_status}",
            f"**locations**: {post.locations or 'N/A'}",
            f"**working_rights**: {post.working_rights or 'N/A'}",
            f"**application_url**: {post.application_url or 'N/A'}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="fix-tags")
    @is_team_member()
    async def fix_tags(self, interaction: discord.Interaction) -> None:
        """Apply Open/Closed tags to all existing forum posts based on their current state."""
        await interaction.response.defer()
        posts = await job_post_db.get_all()
        # A thread whose job is not board-eligible does not belong on the board,
        # whatever its close date says. Without this the command unarchives it
        # for being "open", undoing the board filter every time it is run.
        eligible_ids = await fetch_board_eligible_ids()
        now = datetime.now(tz=timezone.utc)
        updated = skipped = errors = 0

        for post in posts:
            try:
                thread = await interaction.client.fetch_channel(post.forum_post_id)
            except discord.NotFound:
                skipped += 1
                continue
            except Exception:  # noqa: BLE001
                _log.exception(
                    "fix-tags: failed to fetch thread %s", post.forum_post_id
                )
                errors += 1
                continue

            parent = thread.parent
            if parent is None:
                try:
                    parent = await interaction.client.fetch_channel(thread.parent_id)
                except Exception:  # noqa: BLE001
                    skipped += 1
                    continue

            tag_map = {t.name: t for t in parent.available_tags}
            open_tag = tag_map.get("Open")
            closed_tag = tag_map.get("Closed")
            if not open_tag or not closed_tag:
                skipped += 1
                continue

            is_closed = (
                DeadlineReminder.CLOSED in post.deadline_reminders_sent
                or post.outdated
                or (post.close_date is not None and post.close_date < now)
            )
            target = closed_tag if is_closed else open_tag
            remove = open_tag if is_closed else closed_tag

            # Ineligible jobs stay archived, but keep the tag their close date
            # earns: not being board material is not the same as applications
            # having closed, and mislabelling it would be a lie to readers.
            should_archive = is_closed or post.job_id not in eligible_ids
            current_names = {t.name for t in thread.applied_tags}
            tags_correct = (
                target.name in current_names and remove.name not in current_names
            )
            archive_correct = thread.archived == should_archive
            if tags_correct and archive_correct:
                skipped += 1
                continue

            remaining = [
                t for t in thread.applied_tags if t.name not in ("Open", "Closed")
            ]
            new_tags = apply_tag_limit(target, remaining)
            try:
                # Unarchive first if needed so the edit is accepted by Discord.
                if thread.archived:
                    await thread.edit(archived=False, applied_tags=new_tags)
                else:
                    await thread.edit(applied_tags=new_tags)
                # Set final archive state to match job availability.
                if should_archive:
                    await thread.edit(archived=True)
                updated += 1
            except Exception:  # noqa: BLE001
                _log.exception("fix-tags: failed to edit thread %s", thread.id)
                errors += 1

        await interaction.followup.send(
            f"Tag fix complete: **{updated}** updated, **{skipped}** skipped, **{errors}** errors."
        )

    @app_commands.command(name="archive-all")
    @is_team_member()
    async def archive_all(self, interaction: discord.Interaction) -> None:
        """Archive every forum post."""
        await interaction.response.defer()

        posts = await job_post_db.get_all()
        archived = skipped = errors = 0

        for post in posts:
            try:
                thread = await interaction.client.fetch_channel(post.forum_post_id)
            except discord.NotFound:
                skipped += 1
                continue
            except Exception:  # noqa: BLE001
                _log.exception(
                    "archive-all: failed to fetch thread %s", post.forum_post_id
                )
                errors += 1
                continue

            if thread.archived:
                skipped += 1
                continue

            try:
                await thread.edit(archived=True)
                _log.info(
                    "archive-all: archived thread %s (%s)", thread.id, thread.name
                )
                archived += 1
            except Exception:  # noqa: BLE001
                _log.exception("archive-all: failed to archive thread %s", thread.id)
                errors += 1

        await interaction.followup.send(
            f"Done: **{archived}** archived, **{skipped}** already archived/not found, **{errors}** errors."
        )

    @app_commands.command(name="reset-open-state")
    @is_team_member()
    async def reset_open_state(self, interaction: discord.Interaction) -> None:
        """Close all forum posts, then reopen those whose job is still active in the database."""
        await interaction.response.defer()

        posts = await job_post_db.get_all()
        # Reopen only what is both still active and board-eligible. Filtering on
        # "not outdated" alone reopened every thread for a job the board filter
        # excludes, which made this command undo the filter wholesale.
        raw_ids = (
            await job_col._col()
            .find({"outdated": {"$ne": True}, "board_eligible": True}, {"_id": 1})
            .to_list(None)
        )
        active_job_ids = {str(d["_id"]) for d in raw_ids}

        threads: dict[int, discord.Thread] = {}
        close_errors = open_errors = 0

        msg = await interaction.followup.send(
            "Phase 1/2: closing all posts...", wait=True
        )

        # Phase 1: archive every forum post.
        for post in posts:
            try:
                thread = await interaction.client.fetch_channel(post.forum_post_id)
            except discord.NotFound:
                continue
            except Exception:  # noqa: BLE001
                _log.exception(
                    "reset-open-state: failed to fetch thread %s", post.forum_post_id
                )
                close_errors += 1
                continue

            threads[post.forum_post_id] = thread
            if not thread.archived:
                try:
                    await thread.edit(archived=True)
                    _log.info(
                        "reset-open-state: archived thread %s (%s)",
                        thread.id,
                        thread.name,
                    )
                except Exception:  # noqa: BLE001
                    _log.exception(
                        "reset-open-state: failed to archive thread %s", thread.id
                    )
                    close_errors += 1

        await msg.edit(content="Phase 2/2: reopening active posts...")

        # Phase 2: unarchive posts whose job is still in active_jobs.
        opened = 0
        for post in posts:
            if post.job_id not in active_job_ids:
                continue
            thread = threads.get(post.forum_post_id)
            if thread is None:
                continue
            try:
                await thread.edit(archived=False)
                _log.info(
                    "reset-open-state: unarchived thread %s (%s)",
                    thread.id,
                    thread.name,
                )
                opened += 1
            except Exception:  # noqa: BLE001
                _log.exception(
                    "reset-open-state: failed to unarchive thread %s", thread.id
                )
                open_errors += 1

        total_errors = close_errors + open_errors
        await msg.edit(
            content=f"Done: **{opened}** opened, **{len(threads) - opened}** closed, **{total_errors}** errors."
        )

    @app_commands.command(name="diagnose")
    @is_team_member()
    async def diagnose(self, interaction: discord.Interaction) -> None:
        """Report what the bot sees in the database and what the filters make of it.

        "The filter is broken", "the filter works and the scraper marks
        everything eligible" and "the bot is reading the wrong database" all
        look the same from inside Discord, and each needs a different fix.
        """
        await interaction.response.defer(ephemeral=True)
        config = await guild_config_db.get(interaction.guild_id)
        diag = await collect_board_diagnostics(
            interaction.guild_id,
            bot=interaction.client,
            forum_channel_id=config.forum_channel_id if config else None,
        )

        lines = [
            f"**MongoDB database**: `{diag.database}`",
            f"**Documents in active_jobs**: {diag.total}",
            "",
            "**Board eligibility**",
            f"• eligible: {diag.eligible}",
            f"• not eligible: {diag.ineligible}",
            f"• never scored (no field): {diag.unscored}",
            "",
            "**Of the eligible ones**",
            f"• open, would post: {diag.eligible_open}",
            f"• deadline passed: {diag.eligible_closed}",
            f"• outdated: {diag.eligible_outdated}",
            "",
            "**This server**",
            f"• job post records: {diag.records_this_guild}",
            *(
                [f"• threads actually in the forum: {diag.threads_in_forum}"]
                if diag.threads_in_forum >= 0
                else []
            ),
            *(
                [f"• of those, with no database record: {diag.orphan_threads}"]
                if diag.orphan_threads > 0
                else []
            ),
            (
                f"• {command_mention(interaction.client, 'jobs', 'sync')} would "
                f"create: **{diag.would_post}** new thread(s)"
            ),
        ]

        if diag.top_companies:
            lines += ["", "**Most-represented employers among postable jobs**"]
            lines += [f"• {name}: {count}" for name, count in diag.top_companies]

        if diag.unscored and not diag.eligible:
            lines += [
                "",
                (
                    "⚠️ Nothing is scored. The scraper has not run its board "
                    "scoring over this collection, so nothing is postable."
                ),
            ]
        elif diag.orphan_threads > 0:
            lines += [
                "",
                (
                    f"⚠️ {diag.orphan_threads} thread(s) in the forum have no "
                    "record, so no record-driven command can see them. They were "
                    "posted against a database that has since been replaced. "
                    "/jobs rebuild deletes them; nothing else will."
                ),
            ]
        elif diag.records_this_guild > diag.eligible_open + 50:
            lines += [
                "",
                (
                    "⚠️ Far more threads recorded than there are postable jobs. "
                    "That is what a board built before the filter looks like."
                ),
            ]

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(name="rebuild")
    @app_commands.describe(
        confirm=f'Type "{CONFIRM_PHRASE}" to acknowledge this deletes every thread'
    )
    # Team role, matching every other job command. What stops this firing by
    # accident is the typed phrase and the button, not the permission level;
    # gating it on administrator only meant the people who run the board day to
    # day had to find an admin to fix their own forum.
    @is_team_member()
    async def rebuild(self, interaction: discord.Interaction, confirm: str) -> None:
        """Delete every job thread and record in this server, then re-post eligible jobs.

        This exists because archiving cannot rebuild a forum: /jobs sync skips
        any job that already has a JobPost record, so the records have to go for
        the board to be recreated from scratch.

        Destructive and not reversible. Deleting a thread deletes what people
        said in it, including anyone reporting an interview or an offer, so it
        is gated on the team role, a typed phrase and a button, and it says how
        many threads it is about to delete before it does anything.
        """
        if confirm != CONFIRM_PHRASE:
            await interaction.response.send_message(
                f"Rebuild not started. Re-run it with `confirm: {CONFIRM_PHRASE}` "
                "if you really mean to delete every job thread in this server.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Scoped to this guild throughout: a rebuild run in one server must not
        # touch another server's threads or records.
        posts = await job_post_db.get_by_guild(interaction.guild_id)
        config = await guild_config_db.get(interaction.guild_id)

        # The forum is enumerated as well as the records, because the records
        # are the only link between a job and its thread: anything posted
        # against a database that has since been replaced has no record, and is
        # invisible to every record-driven command. Deleting only what is
        # recorded is what leaves a forum full of threads nothing can touch.
        forum_threads: list[discord.Thread] = []
        if config is not None:
            forum_threads = await fetch_all_forum_threads(
                interaction.client, interaction.guild_id, config.forum_channel_id
            )

        recorded_ids = {post.forum_post_id for post in posts}
        orphans = [t for t in forum_threads if t.id not in recorded_ids]
        total = len(posts) + len(orphans)

        if total == 0:
            await interaction.followup.send(
                "Nothing to rebuild: no job post records and no threads in the forum.",
                ephemeral=True,
            )
            return

        # Captured before anything is deleted. A rebuilt thread is new, so it
        # would be stamped with today and the weekly recap would announce the
        # whole board as this week's postings, pinging every role about it --
        # the exact notification the per-post pings were removed to avoid.
        original_posted_at = {post.job_id: post.posted_at for post in posts}

        orphan_note = (
            f"\n\n**{len(orphans)}** of these have no record in the database — "
            "left behind by an earlier deployment, and invisible to every other "
            "command. They are deleted too."
            if orphans
            else ""
        )

        view = RebuildConfirmView(interaction.user.id, total)
        message = await interaction.followup.send(
            f"**This deletes {total} thread(s) in this server, permanently.**\n"
            "Every message in them goes too, including anyone who posted about an "
            "interview or an offer. Archived threads are deleted as well."
            f"{orphan_note}\n\n"
            "Board-eligible jobs are re-posted afterwards as new, empty threads.",
            view=view,
            ephemeral=True,
            wait=True,
        )
        view.message = message

        await view.wait()
        if not view.confirmed:
            return

        deleted = missing = errors = 0
        for post in posts:
            try:
                thread = await interaction.client.fetch_channel(post.forum_post_id)
            except discord.NotFound:
                # Already gone; the record still has to go with it.
                missing += 1
                continue
            except Exception:  # noqa: BLE001
                _log.exception("rebuild: failed to fetch thread %s", post.forum_post_id)
                errors += 1
                continue

            try:
                await thread.delete()
                _log.info("rebuild: deleted thread %s (%s)", thread.id, thread.name)
                deleted += 1
            except Exception:  # noqa: BLE001
                _log.exception("rebuild: failed to delete thread %s", thread.id)
                errors += 1

        orphans_deleted = 0
        for thread in orphans:
            try:
                await thread.delete()
                _log.info(
                    "rebuild: deleted orphaned thread %s (%s)", thread.id, thread.name
                )
                orphans_deleted += 1
            except discord.NotFound:
                missing += 1
            except Exception:  # noqa: BLE001
                _log.exception(
                    "rebuild: failed to delete orphaned thread %s", thread.id
                )
                errors += 1

        # Records are cleared even where a thread failed to delete: a record
        # pointing at a thread that may not exist is what blocks /jobs sync from
        # rebuilding, and a leftover thread is visible and can be removed by
        # hand, whereas a leftover record is invisible and silently suppresses
        # the job forever.
        cleared = await job_post_db.delete_by_guild(interaction.guild_id)
        _log.info(
            "rebuild: guild %s deleted=%d orphans_deleted=%d missing=%d errors=%d "
            "records_cleared=%d",
            interaction.guild_id,
            deleted,
            orphans_deleted,
            missing,
            errors,
            cleared,
        )

        result = await sync_jobs(interaction.client)
        if result.aborted:
            await interaction.followup.send(
                f"Deleted **{deleted + orphans_deleted}** thread(s) and cleared "
                f"**{cleared}** record(s), "
                "but the re-sync aborted: more board-eligible jobs than the safety "
                "limit allows. The forum is empty; check the bot logs and run "
                f"{command_mention(interaction.client, 'jobs', 'sync')} once fixed.",
                ephemeral=True,
            )
            return

        # Jobs that had no thread before keep today's date: they really are new,
        # and should appear in the next recap.
        restored = await job_post_db.restore_posted_at(
            interaction.guild_id, original_posted_at
        )
        _log.info(
            "rebuild: guild %s restored posted_at on %d re-posted job(s)",
            interaction.guild_id,
            restored,
        )

        await interaction.followup.send(
            f"Rebuild complete: **{deleted + orphans_deleted}** thread(s) deleted "
            f"(**{orphans_deleted}** of them orphaned, with no database record), "
            f"**{missing}** already gone, **{errors}** failed, **{cleared}** "
            f"record(s) cleared, **{result.posted}** eligible job(s) re-posted "
            f"(**{restored}** kept their original posting date, so the weekly recap "
            f"still only lists what is genuinely new).",
            ephemeral=True,
        )

    @app_commands.command(name="check-deadlines")
    @is_team_member()
    async def check_deadlines(self, interaction: discord.Interaction) -> None:
        """Manually trigger the deadline checker for all job posts."""
        await interaction.response.defer(ephemeral=True)
        watcher = interaction.client.cogs.get("DeadlineWatcher")
        if watcher is None:
            await interaction.followup.send(
                "Deadline watcher is not loaded.", ephemeral=True
            )
            return
        count = await watcher._run_check()
        _log.info(
            "Guild %s triggered manual deadline check: %d post(s)",
            interaction.guild_id,
            count,
        )
        await interaction.followup.send(
            f"Deadline check complete: **{count}** post(s) checked.", ephemeral=True
        )


class JobsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(JobsGroup())

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("jobs")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JobsCog(bot))
