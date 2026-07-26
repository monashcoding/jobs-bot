import discord
from discord import app_commands


class NotAdmin(app_commands.CheckFailure):
    pass


class NotTeamMember(app_commands.CheckFailure):
    pass


def is_admin() -> app_commands.check:
    """Slash command check that requires the user to have administrator permission."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            raise NotAdmin("You need administrator permission to use this command.")
        return True

    return app_commands.check(predicate)


def is_team_member() -> app_commands.check:
    """Allows users with the configured team_role_id or administrator permission."""
    from src.backend.sql.tables import guild_config_db

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        config = await guild_config_db.get(interaction.guild_id)
        if (
            config
            and config.team_role_id
            and any(r.id == config.team_role_id for r in interaction.user.roles)
        ):
            return True
        raise NotTeamMember("You need to be a team member to use this command.")

    return app_commands.check(predicate)
