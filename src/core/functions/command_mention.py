from __future__ import annotations

from discord.ext import commands


def command_mention(bot: commands.Bot, *path: str) -> str:
    """Return a Discord slash command mention like </jobs config set-forum-channel:123456>.

    Falls back to id=0 (renders as a non-clickable mention) if command IDs
    have not been populated yet (i.e. before on_ready fires).
    """
    cmd_id: int = getattr(bot, "command_ids", {}).get(path[0], 0)
    return f"</{' '.join(path)}:{cmd_id}>"
