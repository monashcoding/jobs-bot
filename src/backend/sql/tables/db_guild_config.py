from __future__ import annotations

from typing import Final

from src.backend.sql.models import GuildConfig
from src.backend.sql.tables.base import BaseDB


class GuildConfigDB(BaseDB[GuildConfig]):
    model = GuildConfig

    async def get_all(self) -> list[GuildConfig]:
        """Return all guild configurations."""
        from sqlmodel import select

        async with self._session() as s:
            result = await s.exec(select(GuildConfig))
            return list(result.all())


guild_config_db: Final[GuildConfigDB] = GuildConfigDB()
