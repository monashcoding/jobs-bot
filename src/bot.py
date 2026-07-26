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


@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    bot.command_ids = {cmd.name: cmd.id for cmd in synced}  # type: ignore[attr-defined]
    _log.info("Logged in as %s (ID: %s), %d commands synced", bot.user, bot.user.id, len(synced))


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


asyncio.run(main())
