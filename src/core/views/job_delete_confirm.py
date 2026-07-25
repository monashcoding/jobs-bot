from __future__ import annotations

import logging

import discord

from src.backend.sql.tables import guild_config_db, job_post_db

_log = logging.getLogger(__name__)


class DeleteConfirmView(discord.ui.View):
    """Persistent view asking whether to delete or keep a job forum post.

    Buttons are role-gated: the interacting member must have the configured
    team_role_id for the guild, or administrator permission.
    """

    def __init__(self, job_id: str, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.job_id = job_id
        self.guild_id = guild_id

        self.add_item(
            _DeleteButton(
                job_id=job_id,
                guild_id=guild_id,
                custom_id=f"job_del_confirm:{job_id}:{guild_id}",
            )
        )
        self.add_item(
            _KeepButton(
                job_id=job_id,
                guild_id=guild_id,
                custom_id=f"job_del_keep:{job_id}:{guild_id}",
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "This action can only be used inside a server.", ephemeral=True
            )
            return False

        if member.guild_permissions.administrator:
            return True

        config = await guild_config_db.get(self.guild_id)
        if config and config.team_role_id:
            if any(r.id == config.team_role_id for r in member.roles):
                return True

        await interaction.response.send_message(
            "You don't have permission to manage job posts.", ephemeral=True
        )
        return False


class _DeleteButton(discord.ui.Button):
    def __init__(self, job_id: str, guild_id: int, custom_id: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Delete Post",
            custom_id=custom_id,
        )
        self.job_id = job_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        post = await job_post_db.get(self.job_id, self.guild_id)
        if post is None:
            await interaction.response.send_message(
                "Job post record not found.", ephemeral=True
            )
            return

        # Delete the forum thread
        try:
            thread = await interaction.client.fetch_channel(post.forum_post_id)
            await thread.delete()
        except discord.NotFound:
            _log.warning("Thread %s not found during deletion.", post.forum_post_id)
        except Exception:
            _log.exception("Failed to delete thread %s", post.forum_post_id)

        # Remove from DB
        await job_post_db.delete(self.job_id, self.guild_id)

        # Disable view and update the prompt message
        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"Post deleted by {interaction.user.mention}.", view=self.view
        )


class _KeepButton(discord.ui.Button):
    def __init__(self, job_id: str, guild_id: int, custom_id: str) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label="Keep Post",
            custom_id=custom_id,
        )
        self.job_id = job_id
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        await job_post_db.clear_awaiting_deletion(self.job_id, self.guild_id)

        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"Post kept by {interaction.user.mention}.", view=self.view
        )
