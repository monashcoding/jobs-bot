from src.backend.sql.models import GuildConfig
from src.backend.sql.tables import GuildConfigDB


async def test_upsert_creates_record(guild_config_db: GuildConfigDB):
    config = GuildConfig(guild_id=1, forum_channel_id=100)
    result = await guild_config_db.upsert(config)
    assert result.guild_id == 1
    assert result.forum_channel_id == 100


async def test_get_returns_record(guild_config_db: GuildConfigDB):
    await guild_config_db.upsert(GuildConfig(guild_id=2, forum_channel_id=200))
    fetched = await guild_config_db.get(2)
    assert fetched is not None
    assert fetched.forum_channel_id == 200


async def test_get_missing_returns_none(guild_config_db: GuildConfigDB):
    result = await guild_config_db.get(9999)
    assert result is None


async def test_upsert_updates_record(guild_config_db: GuildConfigDB):
    await guild_config_db.upsert(GuildConfig(guild_id=3, forum_channel_id=300))
    updated = await guild_config_db.upsert(GuildConfig(guild_id=3, forum_channel_id=301))
    assert updated.forum_channel_id == 301


async def test_delete_existing(guild_config_db: GuildConfigDB):
    await guild_config_db.upsert(GuildConfig(guild_id=4, forum_channel_id=400))
    deleted = await guild_config_db.delete(4)
    assert deleted is True
    assert await guild_config_db.get(4) is None


async def test_delete_missing_returns_false(guild_config_db: GuildConfigDB):
    result = await guild_config_db.delete(9999)
    assert result is False


async def test_get_all(guild_config_db: GuildConfigDB):
    await guild_config_db.upsert(GuildConfig(guild_id=10, forum_channel_id=1000))
    await guild_config_db.upsert(GuildConfig(guild_id=11, forum_channel_id=1001))
    all_configs = await guild_config_db.get_all()
    ids = {c.guild_id for c in all_configs}
    assert {10, 11}.issubset(ids)
