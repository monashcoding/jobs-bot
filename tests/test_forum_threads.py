"""Threads with no JobPost record are invisible to every record-driven command.

The record is the only link between a job and its thread, so anything posted
against a database that has since been replaced cannot be reopened, retagged or
deleted by anything that starts from the records -- which is all of them. That
is why a rebuild deleted 42 threads out of a forum holding far more.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord

from src.core.functions.forum_threads import fetch_all_forum_threads


def _thread(thread_id: int, parent_id: int = 10) -> MagicMock:
    thread = MagicMock(spec=discord.Thread)
    thread.id = thread_id
    thread.parent_id = parent_id
    thread.name = f"thread-{thread_id}"
    return thread


def _bot(active=(), archived=(), *, forum=True) -> MagicMock:
    bot = MagicMock()
    guild = MagicMock()
    guild.active_threads = AsyncMock(return_value=list(active))
    bot.get_guild = MagicMock(return_value=guild)

    channel = MagicMock(spec=discord.ForumChannel) if forum else MagicMock()

    def archived_threads(**kwargs):
        async def gen():
            for t in archived:
                yield t

        return gen()

    channel.archived_threads = archived_threads
    bot.get_channel = MagicMock(return_value=channel)
    return bot


async def test_active_and_archived_are_both_collected():
    # Archived threads are most of a long-lived board: everything older than a
    # week has archived itself, so counting only active ones misses nearly all.
    bot = _bot(active=[_thread(1)], archived=[_thread(2), _thread(3)])

    threads = await fetch_all_forum_threads(bot, guild_id=1, forum_channel_id=10)

    assert {t.id for t in threads} == {1, 2, 3}


async def test_threads_in_other_channels_are_ignored():
    # active_threads() is guild-wide, so it returns threads from every channel.
    bot = _bot(active=[_thread(1, parent_id=10), _thread(99, parent_id=77)])

    threads = await fetch_all_forum_threads(bot, guild_id=1, forum_channel_id=10)

    assert {t.id for t in threads} == {1}


async def test_a_thread_in_both_listings_is_only_counted_once():
    shared = _thread(5)
    bot = _bot(active=[shared], archived=[shared])

    threads = await fetch_all_forum_threads(bot, guild_id=1, forum_channel_id=10)

    assert len(threads) == 1


async def test_a_failure_listing_archived_still_returns_the_active_ones():
    # Partial results beat none: a cleanup that can see some threads is better
    # than one that silently sees zero.
    bot = _bot(active=[_thread(1)])

    def boom(**kwargs):
        raise RuntimeError("cannot list")

    bot.get_channel.return_value.archived_threads = boom

    threads = await fetch_all_forum_threads(bot, guild_id=1, forum_channel_id=10)

    assert {t.id for t in threads} == {1}


async def test_a_non_forum_channel_does_not_raise():
    bot = _bot(active=[_thread(1)], forum=False)

    threads = await fetch_all_forum_threads(bot, guild_id=1, forum_channel_id=10)

    assert {t.id for t in threads} == {1}


async def test_an_unreachable_guild_returns_nothing_rather_than_raising():
    bot = MagicMock()
    bot.get_guild = MagicMock(return_value=None)
    bot.fetch_guild = AsyncMock(side_effect=RuntimeError("no access"))

    assert await fetch_all_forum_threads(bot, guild_id=1, forum_channel_id=10) == []


async def test_diagnose_counts_orphans(job_col=None):
    """The count that would have explained the 42."""
    from src.core.functions import job_diagnostics

    recorded = MagicMock(forum_post_id=1, job_id="a", guild_id=1)
    bot = _bot(active=[_thread(1)], archived=[_thread(2), _thread(3)])

    col = MagicMock()
    col.count_documents = AsyncMock(return_value=0)
    col.find = MagicMock(
        return_value=MagicMock(to_list=AsyncMock(return_value=[])),
    )

    with (
        patch.object(job_diagnostics.job_col, "_col", MagicMock(return_value=col)),
        patch.object(
            job_diagnostics.job_post_db,
            "get_by_guild",
            new=AsyncMock(return_value=[recorded]),
        ),
        patch.object(job_diagnostics, "_top_companies", new=AsyncMock(return_value=[])),
    ):
        diag = await job_diagnostics.collect_board_diagnostics(
            1, bot=bot, forum_channel_id=10
        )

    assert diag.threads_in_forum == 3
    assert diag.records_this_guild == 1
    # Two threads nothing in the database knows about.
    assert diag.orphan_threads == 2
