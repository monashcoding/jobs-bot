import asyncio
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

from src.backend.sql import db

# Uncomment to enable MongoDB (also set MONGODB_URI in your environment):
# from src.backend.mongo import mongo
from src.core.message_utils.paginator import PersistentPaginatorView

_log = logging.getLogger(__name__)

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

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
            print(f"Loaded cog: {ext}")


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


async def main():
    await db.init(os.getenv("DATABASE_URL"))
    # await mongo.init(os.getenv("MONGODB_URI"))  # Uncomment to enable MongoDB
    bot.add_view(PersistentPaginatorView())
    async with bot:
        await load_cogs()
        try:
            await bot.start(os.getenv("DISCORD_TOKEN"))
        finally:
            await db.close()
            # await mongo.close()  # Uncomment to enable MongoDB


asyncio.run(main())
