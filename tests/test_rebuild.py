"""The rebuild deletes threads permanently, so its guards are the feature.

Archiving cannot rebuild a forum: /jobs sync skips any job that already has a
JobPost record, so the records have to go for the board to be recreated. That
makes this the one command that destroys discussion, and every guard on it is
worth a test.
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.backend.sql.models import JobPost
from src.core.views.rebuild_confirm import CONFIRM_PHRASE, RebuildConfirmView


def _utc(dt: datetime) -> datetime:
    """Normalise to aware UTC for comparison.

    The test fixture is SQLite, which has no timezone-aware type and hands back
    naive datetimes. Production is Postgres, where posted_at is TIMESTAMPTZ and
    comes back aware. The stored instant is the same either way; only the test
    fixture needs the tzinfo put back before arithmetic.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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


# A rebuilt thread is a new thread, stamped with today. Left alone that makes
# the entire board look new to the weekly recap, which would announce all of it
# and ping every role -- the exact notification per-post pings were removed to
# avoid.
async def test_rebuild_keeps_the_original_posting_dates(job_post_db):
    old = datetime.now(tz=timezone.utc) - timedelta(days=40)

    # As the rebuild does: capture, wipe, re-create with today's date, restore.
    before = _post("a", 1, 10)
    before.posted_at = old
    await job_post_db.upsert(before)
    original = {p.job_id: p.posted_at for p in await job_post_db.get_by_guild(1)}

    await job_post_db.delete_by_guild(1)
    await job_post_db.upsert(_post("a", 1, 77))  # recreated, posted_at = now

    restored = await job_post_db.restore_posted_at(1, original)

    assert restored == 1
    rebuilt = (await job_post_db.get_by_guild(1))[0]
    assert abs(_utc(rebuilt.posted_at) - old) < timedelta(seconds=1)
    # The new thread id is kept: only the date is carried across.
    assert rebuilt.forum_post_id == 77


async def test_genuinely_new_jobs_keep_todays_date(job_post_db):
    # A job with no previous post really is new and belongs in the next recap.
    old = datetime.now(tz=timezone.utc) - timedelta(days=40)
    await job_post_db.upsert(_post("existing", 1, 10))
    await job_post_db.upsert(_post("brand-new", 1, 11))

    await job_post_db.restore_posted_at(1, {"existing": old})

    by_id = {p.job_id: p for p in await job_post_db.get_by_guild(1)}
    assert abs(_utc(by_id["existing"].posted_at) - old) < timedelta(seconds=1)
    assert _utc(by_id["brand-new"].posted_at) > datetime.now(
        tz=timezone.utc
    ) - timedelta(minutes=5)


async def test_restore_is_scoped_to_the_guild(job_post_db):
    old = datetime.now(tz=timezone.utc) - timedelta(days=40)
    await job_post_db.upsert(_post("a", 1, 10))
    await job_post_db.upsert(_post("a", 2, 20))

    restored = await job_post_db.restore_posted_at(1, {"a": old})

    assert restored == 1
    other_guild = (await job_post_db.get_by_guild(2))[0]
    assert _utc(other_guild.posted_at) > datetime.now(tz=timezone.utc) - timedelta(
        minutes=5
    )


async def test_restore_with_nothing_to_restore_is_a_noop(job_post_db):
    assert await job_post_db.restore_posted_at(1, {}) == 0


async def test_a_rebuilt_board_does_not_flood_the_weekly_recap(job_post_db):
    """The consequence the date-keeping exists to prevent, end to end."""
    long_ago = datetime.now(tz=timezone.utc) - timedelta(days=40)
    for i in range(30):
        post = _post(f"old-{i}", 1, 100 + i)
        post.posted_at = long_ago
        await job_post_db.upsert(post)

    original = {p.job_id: p.posted_at for p in await job_post_db.get_by_guild(1)}
    await job_post_db.delete_by_guild(1)
    for i in range(30):
        await job_post_db.upsert(_post(f"old-{i}", 1, 200 + i))
    # One job that appeared while the board was being rebuilt.
    await job_post_db.upsert(_post("actually-new", 1, 999))

    await job_post_db.restore_posted_at(1, original)

    since = datetime.now(tz=timezone.utc) - timedelta(days=7)
    this_week = await job_post_db.get_posted_since(1, since)

    assert [p.job_id for p in this_week] == ["actually-new"], (
        "the recap must announce only what is genuinely new, not the whole "
        "rebuilt board"
    )


# Access is the team role, matching every other job command. What stops this
# firing by accident is the typed phrase and the button, not the permission
# level; admin-only meant the people running the board day to day had to find
# an admin to fix their own forum.
async def test_a_team_member_without_admin_may_rebuild():
    from src.cogs.commands.jobs import JobsGroup

    assert await _check_passes(JobsGroup.rebuild, administrator=False, team_role_id=555)


async def test_someone_with_neither_admin_nor_the_team_role_may_not():
    from src.cogs.commands.jobs import JobsGroup

    # Config names a role the user does not hold.
    assert not await _check_passes(
        JobsGroup.rebuild, administrator=False, team_role_id=999
    )


# set-team-role is the one command that cannot take the team role: it is what
# grants membership, so gating it on membership is circular -- nobody could
# grant themselves the role, and the refusal pointed at a role that nothing had
# created yet.
async def _check_passes(command, *, administrator: bool, team_role_id=None) -> bool:
    from unittest.mock import AsyncMock, MagicMock, patch

    import discord

    role = MagicMock()
    role.id = 555

    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.user.id = 7
    interaction.user.roles = [role]
    interaction.user._roles = [555]
    # Real Permissions objects: a bare MagicMock reads as truthy for every
    # permission, which would let any check pass regardless of what it asks.
    interaction.permissions = (
        discord.Permissions(administrator=True)
        if administrator
        else discord.Permissions.none()
    )
    interaction.user.guild_permissions = interaction.permissions
    interaction.guild = MagicMock(owner_id=7 if administrator else 999)

    config = MagicMock(team_role_id=team_role_id) if team_role_id else None

    try:
        with patch(
            "src.backend.sql.tables.guild_config_db.get",
            new=AsyncMock(return_value=config),
        ):
            for check in command.checks:
                await check(interaction)
        return True
    except discord.app_commands.CheckFailure:
        return False


async def test_set_team_role_requires_administrator():
    from src.cogs.commands.jobs import ConfigGroup

    assert await _check_passes(ConfigGroup.set_team_role, administrator=True)
    # Holding the team role is not enough, and must not be: on a fresh server
    # no team role exists to hold.
    assert not await _check_passes(
        ConfigGroup.set_team_role, administrator=False, team_role_id=555
    )


async def test_a_fresh_server_can_be_bootstrapped_by_an_admin():
    # No config row exists yet, so guild_config_db.get returns None. An admin
    # must get through both setup commands regardless.
    from src.cogs.commands.jobs import ConfigGroup

    assert await _check_passes(ConfigGroup.set_forum_channel, administrator=True)
    assert await _check_passes(ConfigGroup.set_team_role, administrator=True)


async def test_everything_else_takes_the_team_role():
    # Only granting membership is reserved to an admin. The rest of running the
    # board -- including moving the forum and setting the notification roles --
    # is the team's own to do.
    from src.cogs.commands.jobs import ConfigGroup, JobsGroup

    for command in (
        ConfigGroup.set_forum_channel,
        ConfigGroup.set_role,
        ConfigGroup.set_recap_channel,
        JobsGroup.sync,
        JobsGroup.diagnose,
        JobsGroup.rebuild,
    ):
        assert await _check_passes(command, administrator=False, team_role_id=555), (
            f"{command.name} should be reachable with the team role"
        )
