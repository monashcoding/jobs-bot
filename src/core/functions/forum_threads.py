from __future__ import annotations

import logging
from typing import Final

import discord

_log: Final[logging.Logger] = logging.getLogger(__name__)


async def fetch_all_forum_threads(
    bot: discord.Client, guild_id: int, forum_channel_id: int
) -> list[discord.Thread]:
    """Return every thread in a forum channel, active and archived.

    Asks the API rather than reading ``ForumChannel.threads``, which only holds
    what the cache happens to have: on a cold cache that is nothing, and a
    cleanup that trusted it would silently do less than it claimed.

    This is how threads with no JobPost record are found at all. Records are the
    only link the bot has between a job and its thread, so anything created
    against a database that has since been replaced is invisible to every
    record-driven command -- it just sits in the forum forever.
    """
    threads: dict[int, discord.Thread] = {}

    try:
        guild = bot.get_guild(guild_id) or await bot.fetch_guild(guild_id)
    except Exception:  # noqa: BLE001
        _log.exception("Could not fetch guild %s to enumerate threads", guild_id)
        return []

    # Active threads come from a guild-wide endpoint; filter to this forum.
    try:
        for thread in await guild.active_threads():
            if thread.parent_id == forum_channel_id:
                threads[thread.id] = thread
    except Exception:  # noqa: BLE001
        _log.exception("Could not list active threads in guild %s", guild_id)

    try:
        forum = bot.get_channel(forum_channel_id) or await bot.fetch_channel(
            forum_channel_id
        )
    except Exception:  # noqa: BLE001
        _log.exception("Could not fetch forum channel %s", forum_channel_id)
        return list(threads.values())

    if not isinstance(forum, discord.ForumChannel):
        _log.warning(
            "Channel %s is not a forum channel; not enumerating archived threads",
            forum_channel_id,
        )
        return list(threads.values())

    # Archived threads are unbounded and paginated, and are most of a long-lived
    # board: everything posted more than a week ago has archived itself.
    try:
        async for thread in forum.archived_threads(limit=None):
            threads[thread.id] = thread
    except Exception:  # noqa: BLE001
        _log.exception(
            "Could not list archived threads in forum %s; the count will be "
            "short by however many were not read",
            forum_channel_id,
        )

    return list(threads.values())
