from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime
from typing import Final

import discord

_log: Final[logging.Logger] = logging.getLogger(__name__)

# A cap on one thread's history read. Far past the point where more replies
# change the recap's ordering, and it stops a thread somebody has spammed from
# costing the whole recap a paginated walk.
_MAX_HISTORY: Final[int] = 100


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


# What counts as somebody talking. Discord's own message_count cannot be used
# for this: it counts the bot's deadline warnings, and it counts the system
# message Discord posts every time a thread is renamed -- so a board-wide
# rename gives every thread on it the same "conversation" as a thread people
# actually used. Every live thread on the board reads 2 or 4 by that measure,
# and all of it is renames.
_HUMAN_MESSAGE_TYPES: Final[frozenset[discord.MessageType]] = frozenset(
    {discord.MessageType.default, discord.MessageType.reply}
)


async def thread_reply_counts(
    bot: discord.Client,
    thread_ids: Iterable[int],
    after: datetime,
) -> dict[int, int]:
    """Return how many messages real people posted in each thread since *after*.

    How busy a thread is is a tiebreak in the weekly recap, and nothing stores
    it, so it is read back from Discord here. Counted from the thread's history
    rather than from ``message_count``, because that number answers a different
    question: it includes the bot's own warnings and Discord's rename notices,
    both of which land in every thread whether or not anyone cared about it.

    One history read per thread, bounded by the recap's own window and by
    ``_MAX_HISTORY``. A thread nobody has posted in costs one empty page, which
    is the same shape of work the deadline watcher already does hourly.

    A thread that cannot be read is absent from the result rather than zero, so
    the caller can tell "nobody replied" from "could not tell".
    """
    counts: dict[int, int] = {}

    for thread_id in thread_ids:
        thread = bot.get_channel(thread_id)
        if thread is None:
            try:
                thread = await bot.fetch_channel(thread_id)
            except Exception:  # noqa: BLE001
                _log.warning(
                    "Could not fetch thread %s to count its replies", thread_id
                )
                continue

        if not isinstance(thread, discord.Thread):
            continue

        try:
            replies = 0
            async for message in thread.history(after=after, limit=_MAX_HISTORY):
                if message.author == bot.user:
                    continue
                if message.type not in _HUMAN_MESSAGE_TYPES:
                    continue
                replies += 1
            counts[thread_id] = replies
        except Exception:  # noqa: BLE001
            # A recap ordered by company prominence alone is the previous
            # behaviour, and worth far more than no recap.
            _log.exception(
                "Could not read the history of thread %s; it will rank as quiet",
                thread_id,
            )

    return counts
