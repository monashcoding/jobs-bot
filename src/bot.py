import asyncio
import logging
import os
from pathlib import Path
from typing import Final

import discord
from discord.ext import commands
from dotenv import load_dotenv

from src.backend.mongo import mongo
from src.backend.sql import db
from src.core.message_utils.paginator import PersistentPaginatorView

load_dotenv()

discord.utils.setup_logging()

# Suppress noisy third-party loggers
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("motor").setLevel(logging.WARNING)
logging.getLogger("asyncpg").setLevel(logging.WARNING)

_log: Final[logging.Logger] = logging.getLogger(__name__)

intents = discord.Intents.default()

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: discord.app_commands.AppCommandError
) -> None:
    if isinstance(error, discord.app_commands.CheckFailure):
        msg = str(error) or "You don't have permission to use this command."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return

    # A failed argument conversion is a user-facing problem with a specific
    # cause, but the generic branch below reports only the class name --
    # "Something went wrong: TransformerError" says nothing about which
    # argument, or that the fix might be re-inviting the bot properly.
    if isinstance(error, discord.app_commands.TransformerError):
        _log.error(
            "Failed to convert %r for guild=%s: %s",
            error.value,
            interaction.guild_id,
            error,
            exc_info=error.__cause__ or error,
        )
        msg = (
            f"Could not read that argument: {error}. If this is a channel or "
            "role that plainly exists, the bot may not be properly in this "
            "server -- re-invite it with both the `bot` and "
            "`applications.commands` scopes."
        )
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return

    # Unwrap CommandInvokeError to get the original exception
    original = error.original if hasattr(error, "original") else error
    _log.error("Command error: %s", original, exc_info=original)

    msg = f"Something went wrong: {type(original).__name__}"
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


async def load_cogs():
    for folder in ("commands", "workers"):
        for file in Path(f"src/cogs/{folder}").glob("*.py"):
            if file.name.startswith("_"):
                continue
            ext = f"src.cogs.{folder}.{file.stem}"
            await bot.load_extension(ext)
            _log.info("Loaded cog: %s", ext)


async def sync_commands(bot: commands.Bot, guild_id: str | None) -> list:
    """Register slash commands, and return what was registered.

    With no *guild_id* this syncs globally, which is what a bot serving more
    than one server needs. Discord takes up to an hour to propagate a changed
    global command, and until it does, clients hold the previous definition and
    reject its subcommands as outdated.

    With *guild_id* set, the commands are registered against that one guild
    instead, which Discord applies immediately. Global registrations are removed
    in the same pass: Discord shows guild and global commands side by side, so
    leaving both would list every command twice.

    That makes this single-guild: any other server the bot is in loses its
    commands until the variable is unset. It is a deliberate trade for a bot
    that serves one server and is being deployed repeatedly.
    """
    if not guild_id:
        return await bot.tree.sync()

    try:
        guild = discord.Object(id=int(guild_id))
    except ValueError:
        # A typo here must not stop the bot booting; global sync still works.
        _log.error(
            "DISCORD_GUILD_ID=%r is not a valid ID; syncing globally instead",
            guild_id,
        )
        return await bot.tree.sync()

    _log.warning(
        "DISCORD_GUILD_ID is set: syncing commands to guild %s only. They appear "
        "immediately there, and any other guild loses its commands until this "
        "variable is unset.",
        guild_id,
    )

    # Order matters: copy into the guild bucket first, then empty the global one
    # and push that emptiness, so the global registrations go away without
    # taking the copy with them.
    bot.tree.copy_global_to(guild=guild)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    return await bot.tree.sync(guild=guild)


@bot.event
async def on_ready():
    synced = await sync_commands(bot, os.getenv("DISCORD_GUILD_ID"))
    bot.command_ids = {cmd.name: cmd.id for cmd in synced}  # type: ignore[attr-defined]
    _log.info(
        "Logged in as %s (ID: %s), %d commands synced",
        bot.user,
        bot.user.id,
        len(synced),
    )


async def main():
    _log.info("Starting bot")
    await db.init(os.getenv("DATABASE_URL"))
    await mongo.init(os.getenv("MONGODB_URI"))
    bot.add_view(PersistentPaginatorView())
    async with bot:
        await load_cogs()
        try:
            await bot.start(os.getenv("DISCORD_TOKEN"))
        finally:
            _log.info("Shutting down")
            await db.close()
            await mongo.close()


if __name__ == "__main__":
    # Guarded so the module can be imported -- by tests, or by anything wanting
    # sync_commands -- without starting a bot. `python -m src.bot` still runs it.
    asyncio.run(main())
