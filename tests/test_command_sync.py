"""Global slash commands take up to an hour to propagate.

Until they do, clients hold the previous definition of the /jobs group and
reject its subcommands as outdated. Syncing to a single guild is immediate,
which matters when the bot is being redeployed repeatedly.
"""

from unittest.mock import AsyncMock, MagicMock

from src.bot import sync_commands


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.tree.sync = AsyncMock(return_value=[MagicMock(name="cmd")])
    bot.tree.copy_global_to = MagicMock()
    bot.tree.clear_commands = MagicMock()
    return bot


async def test_no_guild_id_syncs_globally():
    bot = _bot()

    await sync_commands(bot, None)

    bot.tree.sync.assert_awaited_once_with()
    bot.tree.copy_global_to.assert_not_called()


async def test_empty_guild_id_is_treated_as_unset():
    # An env var present but blank is the normal way of turning this off.
    bot = _bot()

    await sync_commands(bot, "")

    bot.tree.sync.assert_awaited_once_with()


async def test_guild_id_syncs_to_that_guild():
    bot = _bot()

    await sync_commands(bot, "123456789")

    bot.tree.copy_global_to.assert_called_once()
    assert bot.tree.copy_global_to.call_args.kwargs["guild"].id == 123456789

    guild_syncs = [
        c for c in bot.tree.sync.await_args_list if c.kwargs.get("guild") is not None
    ]
    assert len(guild_syncs) == 1
    assert guild_syncs[0].kwargs["guild"].id == 123456789


async def test_global_commands_are_cleared_so_they_are_not_listed_twice():
    # Discord shows guild and global commands side by side, so leaving both
    # registered lists every command twice.
    bot = _bot()

    await sync_commands(bot, "123456789")

    bot.tree.clear_commands.assert_called_once_with(guild=None)


async def test_the_copy_happens_before_the_global_clear():
    """Order is the whole trick.

    clear_commands(guild=None) empties the global bucket. Copying after it
    would copy nothing, and the guild would end up with no commands at all.
    """
    bot = _bot()
    calls: list[str] = []
    bot.tree.copy_global_to = MagicMock(side_effect=lambda **kw: calls.append("copy"))
    bot.tree.clear_commands = MagicMock(side_effect=lambda **kw: calls.append("clear"))

    await sync_commands(bot, "123456789")

    assert calls == ["copy", "clear"]


async def test_a_malformed_guild_id_falls_back_to_a_global_sync():
    # A typo in an env var must not stop the bot booting.
    bot = _bot()

    result = await sync_commands(bot, "not-a-number")

    bot.tree.sync.assert_awaited_once_with()
    bot.tree.copy_global_to.assert_not_called()
    assert result == bot.tree.sync.return_value


async def test_returns_the_commands_that_were_registered():
    # command_mention reads ids off this, so it must be the guild sync's result
    # rather than the global one when a guild is configured.
    bot = _bot()
    guild_result = [MagicMock()]

    async def sync(**kwargs):
        return guild_result if kwargs.get("guild") is not None else []

    bot.tree.sync = AsyncMock(side_effect=sync)

    assert await sync_commands(bot, "123456789") == guild_result
