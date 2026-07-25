from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.backend.sql.models import GuildConfig
from src.backend.sql.tables import guild_config_db
from src.core.checks import is_admin
from src.core.functions.job_post import sync_jobs


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
        config = GuildConfig(
            guild_id=interaction.guild_id,
            forum_channel_id=channel.id,
            team_role_id=existing.team_role_id if existing else None,
        )
        await guild_config_db.upsert(config)
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
                "Please set a forum channel first with `/jobs config set-forum-channel`.",
                ephemeral=True,
            )
            return
        existing.team_role_id = role.id
        await guild_config_db.upsert(existing)
        await interaction.response.send_message(
            f"{role.mention} can now manage job post deletions.", ephemeral=True
        )

    @app_commands.command(name="view")
    @is_admin()
    async def view_config(self, interaction: discord.Interaction) -> None:
        """Display the current jobs configuration for this guild."""
        config = await guild_config_db.get(interaction.guild_id)
        if config is None:
            await interaction.response.send_message(
                "No configuration found. Use `/jobs config set-forum-channel` to get started.",
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

        embed = discord.Embed(
            title="Jobs Configuration", colour=discord.Colour.blurple()
        )
        embed.add_field(name="Forum Channel", value=forum_mention, inline=False)
        embed.add_field(name="Team Role", value=role_mention, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class JobsGroup(app_commands.Group, name="jobs"):
    """Job board configuration commands."""

    def __init__(self) -> None:
        super().__init__()
        self.add_command(ConfigGroup())

    @app_commands.command(name="sync")
    @is_admin()
    async def sync(self, interaction: discord.Interaction) -> None:
        """Reconcile all active jobs from MongoDB against Discord forum posts."""
        await interaction.response.defer(ephemeral=True)
        result = await sync_jobs(interaction.client)
        await interaction.followup.send(
            f"Sync complete — **{result.posted}** posted, **{result.skipped}** already existed.",
            ephemeral=True,
        )


class JobsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(JobsGroup())

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("jobs")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JobsCog(bot))
