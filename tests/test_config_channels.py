"""Configuring a server must not depend on the bot's cache being warm.

A `discord.ForumChannel` annotation makes discord.py resolve the picked channel
via AppCommandChannel.resolve(), which reads the guild out of cache and returns
None when it is not there. The command then dies with an opaque
TransformerError before any of its own code runs -- on a new server, that is
every attempt.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord import app_commands

from src.backend.sql.models import GuildConfig
from src.cogs.commands.jobs import ConfigGroup


def _channel(channel_type: discord.ChannelType, channel_id: int = 42) -> MagicMock:
    channel = MagicMock(spec=app_commands.AppCommandChannel)
    channel.id = channel_id
    channel.type = channel_type
    channel.mention = f"<#{channel_id}>"
    return channel


def _interaction() -> MagicMock:
    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.response.send_message = AsyncMock()
    return interaction


def test_the_annotation_does_not_resolve_through_the_cache():
    """The regression guard.

    discord.ForumChannel here would reintroduce the cache lookup, and the
    failure only shows up on a server the bot has not cached -- which no test
    with a mocked interaction would ever reproduce.
    """
    for command in (ConfigGroup.set_forum_channel, ConfigGroup.set_recap_channel):
        param = command._params["channel"]
        assert param.type is discord.AppCommandOptionType.channel
        # RawChannelTransformer returns the payload object as-is.
        # BaseChannelTransformer subclasses call .resolve(), which is the cache.
        assert isinstance(
            param._annotation, app_commands.transformers.RawChannelTransformer
        ), f"{command.name} must read the channel from the payload, not the cache"


async def test_a_forum_channel_is_accepted():
    interaction = _interaction()
    upsert = AsyncMock()

    with (
        patch(
            "src.cogs.commands.jobs.guild_config_db.get",
            new=AsyncMock(return_value=None),
        ),
        patch("src.cogs.commands.jobs.guild_config_db.upsert", new=upsert),
    ):
        await ConfigGroup.set_forum_channel.callback(
            ConfigGroup(), interaction, _channel(discord.ChannelType.forum)
        )

    saved: GuildConfig = upsert.await_args.args[0]
    assert saved.forum_channel_id == 42
    assert saved.guild_id == 1


async def test_a_text_channel_is_refused_with_a_usable_message():
    # Discord's picker no longer filters for us, so the check has to say what
    # was wrong rather than failing opaquely.
    interaction = _interaction()
    upsert = AsyncMock()

    with (
        patch(
            "src.cogs.commands.jobs.guild_config_db.get",
            new=AsyncMock(return_value=None),
        ),
        patch("src.cogs.commands.jobs.guild_config_db.upsert", new=upsert),
    ):
        await ConfigGroup.set_forum_channel.callback(
            ConfigGroup(), interaction, _channel(discord.ChannelType.text)
        )

    upsert.assert_not_awaited()
    assert "not a forum channel" in interaction.response.send_message.await_args.args[0]


async def test_media_channels_are_still_accepted():
    # The ForumChannel annotation accepted forum and media; that is preserved.
    interaction = _interaction()
    upsert = AsyncMock()

    with (
        patch(
            "src.cogs.commands.jobs.guild_config_db.get",
            new=AsyncMock(return_value=None),
        ),
        patch("src.cogs.commands.jobs.guild_config_db.upsert", new=upsert),
    ):
        await ConfigGroup.set_forum_channel.callback(
            ConfigGroup(), interaction, _channel(discord.ChannelType.media)
        )

    upsert.assert_awaited_once()


async def test_recap_channel_refuses_a_forum():
    interaction = _interaction()
    upsert = AsyncMock()
    audience = MagicMock(value="intern", name="Internships")

    with (
        patch(
            "src.cogs.commands.jobs.guild_config_db.get",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch("src.cogs.commands.jobs.guild_config_db.upsert", new=upsert),
    ):
        await ConfigGroup.set_recap_channel.callback(
            ConfigGroup(), interaction, audience, _channel(discord.ChannelType.forum)
        )

    upsert.assert_not_awaited()
    assert "not a text channel" in interaction.response.send_message.await_args.args[0]
