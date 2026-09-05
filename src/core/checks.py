from __future__ import annotations

import logging
from typing import Final

import discord
from discord import app_commands

_log: Final[logging.Logger] = logging.getLogger(__name__)


class NotAdmin(app_commands.CheckFailure):
    pass


class NotTeamMember(app_commands.CheckFailure):
    pass


def has_administrator(interaction: discord.Interaction) -> bool:
    """Return True if the invoker has administrator permission.

    Prefers ``interaction.permissions``, which Discord resolves server-side and
    sends in the interaction payload. ``Member.guild_permissions`` is computed
    from the cache instead -- it reads ``guild.owner_id`` and maps the member's
    role IDs through the cached guild -- so when the guild is not cached it
    returns no permissions at all, and even the server owner is refused.
    """
    if interaction.permissions.administrator:
        return True

    # Ownership, in case the payload is ever absent.
    guild = interaction.guild
    if guild is not None and guild.owner_id == interaction.user.id:
        return True

    # Last resort, and the one that needs the cache.
    perms = getattr(interaction.user, "guild_permissions", None)
    return bool(perms and perms.administrator)


def has_role(user: discord.abc.User, role_id: int) -> bool:
    """Return True if *user* holds the role with *role_id*.

    ``Member.roles`` resolves role IDs against the cached guild and silently
    drops any it cannot find, so an uncached guild makes every member look
    unroled. The raw IDs from the interaction payload are checked as well.
    """
    roles = getattr(user, "roles", None)
    if roles and any(r.id == role_id for r in roles):
        return True

    # Populated straight from the interaction payload, so it survives a cache miss.
    raw = getattr(user, "_roles", None)
    try:
        return bool(raw is not None and role_id in raw)
    except TypeError:
        return False


# The predicates are module-level rather than closures so they can be called
# directly. A check built by app_commands.check() is a decorator, and the
# predicate inside it is not reachable afterwards, which left the rules that
# decide who may delete the board impossible to test.


async def admin_predicate(interaction: discord.Interaction) -> bool:
    if has_administrator(interaction):
        return True
    _log.info(
        "Admin check failed: user=%s guild=%s resolved_permissions=%s",
        interaction.user.id,
        interaction.guild_id,
        interaction.permissions.value,
    )
    raise NotAdmin("You need administrator permission to use this command.")


async def team_member_predicate(interaction: discord.Interaction) -> bool:
    from src.backend.sql.tables import guild_config_db

    if has_administrator(interaction):
        return True

    config = await guild_config_db.get(interaction.guild_id)
    if (
        config
        and config.team_role_id
        and has_role(interaction.user, config.team_role_id)
    ):
        return True

    # Logged because the three ways to fail here are indistinguishable from the
    # message: no config, no team role set, or the role not held.
    _log.info(
        "Team check failed: user=%s guild=%s config=%s team_role=%s",
        interaction.user.id,
        interaction.guild_id,
        config is not None,
        getattr(config, "team_role_id", None),
    )
    if config is None or not config.team_role_id:
        raise NotTeamMember(
            "No team role has been set for this server yet. An administrator "
            "needs to run /jobs config set-team-role first."
        )
    raise NotTeamMember("You need to be a team member to use this command.")


def is_admin() -> app_commands.check:
    """Slash command check that requires the user to have administrator permission."""
    return app_commands.check(admin_predicate)


def is_team_member() -> app_commands.check:
    """Allows users with the configured team_role_id or administrator permission."""
    return app_commands.check(team_member_predicate)
