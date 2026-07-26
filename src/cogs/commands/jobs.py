from __future__ import annotations

import logging
import time
from typing import Final

import discord
from discord import app_commands
from discord.ext import commands

from src.backend.sql.models import GuildConfig
from src.backend.sql.tables import guild_config_db
from src.core.checks import is_admin, is_team_member
from src.core.functions.command_mention import command_mention
from src.core.functions.job_post import SyncResult, sync_jobs

_log: Final[logging.Logger] = logging.getLogger(__name__)


class ConfigGroup(app_commands.Group, name="config"):
    """Subcommands for configuring the jobs integration."""

    @app_commands.command(name="set-forum-channel")
    @app_commands.describe(channel="The forum channel where job posts will be created")
    @is_admin()
    async def set_forum_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.ForumChannel,
    ) -> None:
        """Set the forum channel for job posts in this guild."""
        existing = await guild_config_db.get(interaction.guild_id)
        if existing:
            existing.forum_channel_id = channel.id
            config = existing
        else:
            config = GuildConfig(guild_id=interaction.guild_id, forum_channel_id=channel.id)
        await guild_config_db.upsert(config)
        _log.info(
            "Guild %s set forum channel to %s", interaction.guild_id, channel.id
        )
        await interaction.response.send_message(
            f"Job posts will be created in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="set-team-role")
    @app_commands.describe(role="The role that can manage (delete/keep) job posts")
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

    @app_commands.command(name="set-role")
    @app_commands.describe(
        job_type="The job type to set the notification role for",
        role="The role to ping when a new post of this type is created",
    )
    @app_commands.choices(job_type=[
        app_commands.Choice(name="Intern/Student", value="intern"),
        app_commands.Choice(name="Graduate", value="grad"),
        app_commands.Choice(name="Junior (1-3 yoe)", value="junior"),
        app_commands.Choice(name="Experienced (4+ yoe)", value="experienced"),
    ])
    @is_admin()
    async def set_role(
        self,
        interaction: discord.Interaction,
        job_type: app_commands.Choice[str],
        role: discord.Role,
    ) -> None:
        """Set the notification role pinged when a new job post of a given type is created."""
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
            f"{role.mention} will be pinged for **{job_type.name}** posts.", ephemeral=True
        )

    @app_commands.command(name="view")
    @is_admin()
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
                f"🌱 Junior (1-3 yoe): {role_mention_or(config.junior_role_id)}\n"
                f"💼 Experienced (4+ yoe): {role_mention_or(config.experienced_role_id)}"
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
        await msg.edit(
            content=f"Sync complete: **{result.posted}** posted, **{result.skipped}** already existed."
        )


    @app_commands.command(name="check-deadlines")
    @is_team_member()
    async def check_deadlines(self, interaction: discord.Interaction) -> None:
        """Manually trigger the deadline checker for all job posts."""
        await interaction.response.defer(ephemeral=True)
        watcher = interaction.client.cogs.get("DeadlineWatcher")
        if watcher is None:
            await interaction.followup.send("Deadline watcher is not loaded.", ephemeral=True)
            return
        count = await watcher._run_check()
        _log.info("Guild %s triggered manual deadline check: %d post(s)", interaction.guild_id, count)
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
