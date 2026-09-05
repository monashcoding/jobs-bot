"""Permission checks must not depend on the bot's cache.

Member.guild_permissions is computed from cache -- it reads guild.owner_id and
maps role IDs through the cached guild -- so an uncached guild made even the
server owner read as having no permissions, and every member as unroled.
Discord resolves both in the interaction payload; that is what gets used.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.core.checks import (
    admin_predicate,
    has_administrator,
    has_role,
    team_member_predicate,
)


def _interaction(
    *,
    resolved_admin: bool = False,
    cached_admin: bool | None = False,
    owner: bool = False,
    guild_cached: bool = True,
    user_id: int = 7,
    roles: list[int] | None = None,
    raw_roles: list[int] | None = None,
) -> MagicMock:
    interaction = MagicMock()
    interaction.guild_id = 1
    interaction.user.id = user_id
    interaction.permissions = (
        discord.Permissions(administrator=True)
        if resolved_admin
        else discord.Permissions.none()
    )

    if guild_cached:
        interaction.guild = MagicMock(owner_id=user_id if owner else 999)
    else:
        interaction.guild = None

    if cached_admin is None:
        del interaction.user.guild_permissions
    else:
        interaction.user.guild_permissions = discord.Permissions(
            administrator=cached_admin
        )

    if roles is None:
        interaction.user.roles = []
    else:
        interaction.user.roles = [MagicMock(id=r) for r in roles]
    interaction.user._roles = raw_roles if raw_roles is not None else []
    return interaction


def test_resolved_payload_permission_is_enough():
    # The cache says nothing and the guild is not even present; Discord's own
    # resolution must still be believed.
    assert has_administrator(
        _interaction(resolved_admin=True, cached_admin=False, guild_cached=False)
    )


def test_owner_passes_without_the_payload_bit():
    assert has_administrator(_interaction(owner=True))


def test_cached_permission_still_works_as_a_fallback():
    assert has_administrator(_interaction(cached_admin=True))


def test_a_user_object_without_guild_permissions_does_not_raise():
    # In odd contexts interaction.user can lack the attribute entirely.
    assert not has_administrator(_interaction(cached_admin=None))


def test_plain_member_is_not_an_admin():
    assert not has_administrator(_interaction())


def test_role_found_through_the_cache():
    user = MagicMock(roles=[MagicMock(id=555)], _roles=[])
    assert has_role(user, 555)


def test_role_found_through_the_raw_payload_when_the_cache_is_empty():
    # The failure this exists for: an uncached guild drops every role from
    # Member.roles, so a team member looks unroled.
    user = MagicMock(roles=[], _roles=[555])
    assert has_role(user, 555)


def test_role_absent_from_both():
    user = MagicMock(roles=[MagicMock(id=1)], _roles=[2])
    assert not has_role(user, 555)


async def test_owner_passes_is_admin_with_a_cold_cache():
    check = admin_predicate
    interaction = _interaction(resolved_admin=True, guild_cached=False)
    assert await check(interaction)


async def test_is_admin_refuses_a_non_admin():
    check = admin_predicate
    with pytest.raises(discord.app_commands.CheckFailure):
        await check(_interaction())


async def test_team_member_passes_on_raw_roles_alone():
    check = team_member_predicate
    interaction = _interaction(roles=[], raw_roles=[555])

    with patch(
        "src.backend.sql.tables.guild_config_db.get",
        new=AsyncMock(return_value=MagicMock(team_role_id=555)),
    ):
        assert await check(interaction)


async def test_missing_team_role_says_so_rather_than_blaming_the_user():
    # "You need to be a team member" is misleading when no team role exists;
    # it sends someone looking for a role nothing has created.
    check = team_member_predicate

    with (
        patch(
            "src.backend.sql.tables.guild_config_db.get",
            new=AsyncMock(return_value=None),
        ),
        pytest.raises(discord.app_commands.CheckFailure) as exc,
    ):
        await check(_interaction())

    assert "set-team-role" in str(exc.value)
