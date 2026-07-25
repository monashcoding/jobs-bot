import discord
from discord import app_commands


class NotAdmin(app_commands.CheckFailure):
    pass


def is_admin() -> app_commands.check:
    """Slash command check that requires the user to have administrator permission."""

    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            raise NotAdmin("You need administrator permission to use this command.")
        return True

    return app_commands.check(predicate)
