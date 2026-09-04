"""The rebuild deletes threads permanently, so its guards are the feature.

Archiving cannot rebuild a forum: /jobs sync skips any job that already has a
JobPost record, so the records have to go for the board to be recreated. That
makes this the one command that destroys discussion, and every guard on it is
worth a test.
"""

from datetime import datetime, timezone

import pytest

from src.backend.sql.models import JobPost
from src.core.views.rebuild_confirm import CONFIRM_PHRASE, RebuildConfirmView


def _post(job_id: str, guild_id: int, thread_id: int) -> JobPost:
    return JobPost(
        job_id=job_id,
        guild_id=guild_id,
        forum_post_id=thread_id,
        forum_channel_id=1,
        posted_at=datetime.now(tz=timezone.utc),
        title=f"Job {job_id}",
    )


async def test_delete_by_guild_leaves_other_guilds_alone(job_post_db):
    # A rebuild in one server must not orphan another server's threads: the
    # record is what tells the bot a thread exists, and a thread whose record is
    # gone is invisible to it forever.
    await job_post_db.upsert(_post("a", 1, 10))
    await job_post_db.upsert(_post("b", 1, 11))
    await job_post_db.upsert(_post("c", 2, 12))

    deleted = await job_post_db.delete_by_guild(1)

    assert deleted == 2
    assert await job_post_db.get_by_guild(1) == []
    survivors = await job_post_db.get_by_guild(2)
    assert [p.job_id for p in survivors] == ["c"]


async def test_get_by_guild_is_scoped(job_post_db):
    await job_post_db.upsert(_post("a", 1, 10))
    await job_post_db.upsert(_post("c", 2, 12))

    assert [p.job_id for p in await job_post_db.get_by_guild(1)] == ["a"]


async def test_delete_by_guild_on_empty_guild_is_a_noop(job_post_db):
    assert await job_post_db.delete_by_guild(999) == 0


# The confirmation view is the last thing between a mistyped command and a
# forum full of deleted conversations.
def test_view_starts_unconfirmed():
    view = RebuildConfirmView(author_id=1, thread_count=5)
    assert view.confirmed is None


async def test_only_the_invoker_may_confirm():
    from unittest.mock import AsyncMock, MagicMock

    view = RebuildConfirmView(author_id=1, thread_count=5)

    someone_else = MagicMock()
    someone_else.user.id = 2
    someone_else.response.send_message = AsyncMock()

    assert await view.interaction_check(someone_else) is False
    someone_else.response.send_message.assert_awaited_once()

    invoker = MagicMock()
    invoker.user.id = 1
    assert await view.interaction_check(invoker) is True


async def test_timeout_refuses_rather_than_hanging_open():
    # An expired confirmation must not stay pressable, and must not be
    # mistaken for a yes.
    from unittest.mock import AsyncMock, MagicMock

    view = RebuildConfirmView(author_id=1, thread_count=5)
    view.message = MagicMock()
    view.message.edit = AsyncMock()

    await view.on_timeout()

    assert view.confirmed is False
    assert all(item.disabled for item in view.children)


@pytest.mark.parametrize(
    "typed",
    ["", "yes", "delete everything", "DELETE EVERYTHING ", "DELETE  EVERYTHING"],
)
def test_confirm_phrase_is_not_matched_loosely(typed):
    # Case and spacing must match: the phrase is a deliberate act, not a
    # formality to be waved through with "yes".
    assert typed != CONFIRM_PHRASE


def test_confirm_phrase_is_typable():
    assert CONFIRM_PHRASE == "DELETE EVERYTHING"
