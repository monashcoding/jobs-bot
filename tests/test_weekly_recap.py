"""The weekly recap is now the only thing that pings.

Job posts used to mention a role on creation, which at scrape volume meant a
notification per job. The recap collects the week into one message per audience.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.sql.models import GuildConfig, JobPost
from src.cogs.workers.weekly_recap import (
    _MAX_LISTED,
    WeeklyRecap,
    audience_for,
    build_recap,
    recap_order,
    role_mentions,
)
from src.core.functions.job_post import GRAD_AUDIENCE, INTERN_AUDIENCE


def _post(
    title: str,
    job_type: str | None,
    guild_id: int = 1,
    company_name: str = "",
    company_tier: str | None = None,
) -> JobPost:
    return JobPost(
        job_id=title,
        guild_id=guild_id,
        forum_post_id=999,
        forum_channel_id=1,
        posted_at=datetime.now(tz=timezone.utc),
        title=title,
        job_type=job_type,
        company_name=company_name,
        company_tier=company_tier,
    )


def test_audience_routing():
    assert audience_for("INTERN") == INTERN_AUDIENCE
    assert audience_for("GRADUATE") == GRAD_AUDIENCE
    assert audience_for("FULL_TIME") == GRAD_AUDIENCE
    # Unknown or missing type goes to the wider audience rather than vanishing.
    assert audience_for(None) == GRAD_AUDIENCE
    assert audience_for("SOMETHING_NEW") == GRAD_AUDIENCE


def test_build_recap_lists_jobs_and_pings():
    posts = [_post("Backend Engineer", "INTERN"), _post("Data Intern", "INTERN")]
    message = build_recap(posts, INTERN_AUDIENCE, "<@&42>", 555)

    assert "<@&42>" in message
    assert "2 new internship roles" in message
    assert "Backend Engineer" in message
    assert "Data Intern" in message


def test_build_recap_singular():
    message = build_recap([_post("Solo Role", "INTERN")], INTERN_AUDIENCE, "", 555)
    assert "1 new internship role this week" in message


# Discord rejects messages over 2000 characters, and a busy week can exceed it.
def test_build_recap_stays_within_discord_limit():
    posts = [
        _post(f"Very Long Job Title Number {i}" * 3, "GRADUATE") for i in range(80)
    ]
    message = build_recap(posts, GRAD_AUDIENCE, "<@&1> <@&2>", 555)

    assert len(message) < 2000
    assert "80 new graduate roles" in message


# The recap is a prompt to open the board, not a copy of it.
def test_build_recap_lists_at_most_the_cap():
    posts = [_post(f"Role {i}", "GRADUATE") for i in range(30)]
    message = build_recap(posts, GRAD_AUDIENCE, "", 555)

    assert message.count("\u2022 [") == _MAX_LISTED
    assert "30 new graduate roles" in message


# The count is the only thing telling the reader the list is partial, so it has
# to survive both the entry cap and the character backstop.
def test_overflow_line_links_the_board_and_counts_the_rest():
    posts = [_post(f"Role {i}", "GRADUATE") for i in range(30)]
    assert f"\u2026and {30 - _MAX_LISTED} more in <#555>." in build_recap(
        posts, GRAD_AUDIENCE, "", 555
    )

    # Titles long enough that the character budget, not the cap, ends the list.
    huge = [_post("T" * 400, "GRADUATE") for _ in range(30)]
    message = build_recap(huge, GRAD_AUDIENCE, "", 555)
    listed = message.count("\u2022 [")
    assert listed < _MAX_LISTED
    assert f"\u2026and {30 - listed} more in <#555>." in message
    assert len(message) < 2000


def test_no_overflow_line_when_everything_fits():
    posts = [_post(f"Role {i}", "GRADUATE") for i in range(_MAX_LISTED)]
    assert "more in <#" not in build_recap(posts, GRAD_AUDIENCE, "", 555)


# Every posting on the board already cleared the scraper's company gate, so the
# recap orders by prominence to decide which of them earn the visible slots.
def test_recap_orders_headline_companies_first():
    posts = [
        _post("Role A", "GRADUATE", company_tier="unranked"),
        _post("Role B", "GRADUATE", company_tier="major"),
        _post("Role C", "GRADUATE", company_tier="headline"),
    ]
    assert [p.title for p in recap_order(posts)] == ["Role C", "Role B", "Role A"]


# Documents written before the scraper emitted a tier still have to sort, so the
# recap falls back to the bot's own company list rather than dropping them all
# to the bottom together.
def test_recap_falls_back_to_the_company_list_when_untiered():
    posts = [
        _post("Role A", "GRADUATE", company_name="Some Unknown Startup"),
        _post("Role B", "GRADUATE", company_name="Deloitte"),
        _post("Role C", "GRADUATE", company_name="Atlassian"),
    ]
    assert [p.title for p in recap_order(posts)] == ["Role C", "Role B", "Role A"]


# A tiered and an untiered posting have to interleave correctly, or the week the
# scraper ships reads as two separate lists stapled together.
def test_tiered_and_untiered_postings_sort_together():
    posts = [
        _post("Untiered major", "GRADUATE", company_name="Deloitte"),
        _post("Tiered headline", "GRADUATE", company_tier="headline"),
        _post("Untiered headline", "GRADUATE", company_name="Atlassian"),
        _post("Tiered unranked", "GRADUATE", company_tier="unranked"),
    ]
    assert [p.title for p in recap_order(posts)] == [
        "Tiered headline",
        "Untiered headline",
        "Untiered major",
        "Tiered unranked",
    ]


# The tier is authoritative where it exists: the scraper owns the list, so it
# wins over whatever the bot's own tables think of the name.
def test_the_scrapers_tier_beats_the_local_list():
    posts = [
        _post("Demoted", "GRADUATE", company_name="Atlassian", company_tier="major"),
        _post(
            "Promoted",
            "GRADUATE",
            company_name="Some Unknown Startup",
            company_tier="headline",
        ),
    ]
    assert [p.title for p in recap_order(posts)] == ["Promoted", "Demoted"]


def test_recap_order_is_stable_within_a_tier():
    posts = [
        _post("First", "GRADUATE", company_tier="headline"),
        _post("Second", "GRADUATE", company_tier="headline"),
        _post("Third", "GRADUATE", company_tier="headline"),
    ]
    assert [p.title for p in recap_order(posts)] == ["First", "Second", "Third"]


def test_headline_companies_win_the_visible_slots():
    posts = [
        _post(f"Filler {i}", "GRADUATE", company_tier="major") for i in range(20)
    ] + [_post("The Good One", "GRADUATE", company_tier="headline")]

    assert "The Good One" in build_recap(posts, GRAD_AUDIENCE, "", 555)


def test_role_mentions_skips_unconfigured_roles():
    config = GuildConfig(
        guild_id=1, forum_channel_id=1, grad_role_id=7, professional_role_id=None
    )
    assert role_mentions(config, GRAD_AUDIENCE) == "<@&7>"

    empty = GuildConfig(guild_id=1, forum_channel_id=1)
    assert role_mentions(empty, INTERN_AUDIENCE) == ""


# Each audience gets its own channel, so interns are not pinged about graduate
# roles and vice versa.
async def test_recaps_go_to_separate_channels_per_audience():
    config = GuildConfig(
        guild_id=1,
        forum_channel_id=1,
        intern_role_id=10,
        grad_role_id=20,
        intern_recap_channel_id=100,
        grad_recap_channel_id=200,
    )
    posts = [
        _post("Intern Role", "INTERN"),
        _post("Grad Role", "GRADUATE"),
        _post("Professional Role", "FULL_TIME"),
    ]

    sent: dict[int, str] = {}

    def fake_channel(channel_id):
        channel = MagicMock()

        async def send(message, **kwargs):
            sent[channel_id] = message

        channel.send = send
        return channel

    bot = MagicMock()
    bot.get_channel = fake_channel

    cog = WeeklyRecap(bot)
    with (
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.get_all",
            new=AsyncMock(return_value=[config]),
        ),
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.upsert",
            new=AsyncMock(),
        ),
        patch(
            "src.cogs.workers.weekly_recap.job_post_db.get_posted_since",
            new=AsyncMock(return_value=posts),
        ),
    ):
        await cog.post_recaps(datetime.now(tz=timezone.utc))

    assert set(sent) == {100, 200}
    assert "Intern Role" in sent[100]
    assert "<@&10>" in sent[100]
    assert "Grad Role" in sent[200]
    assert "Professional Role" in sent[200]
    # An intern must not be pinged about graduate roles.
    assert "Intern Role" not in sent[200]
    assert "<@&20>" in sent[200]


async def test_audience_without_a_channel_is_skipped_not_misrouted():
    config = GuildConfig(
        guild_id=1, forum_channel_id=1, grad_recap_channel_id=200, grad_role_id=20
    )
    posts = [_post("Intern Role", "INTERN"), _post("Grad Role", "GRADUATE")]

    sent: dict[int, str] = {}

    def fake_channel(channel_id):
        channel = MagicMock()

        async def send(message, **kwargs):
            sent[channel_id] = message

        channel.send = send
        return channel

    bot = MagicMock()
    bot.get_channel = fake_channel

    cog = WeeklyRecap(bot)
    with (
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.get_all",
            new=AsyncMock(return_value=[config]),
        ),
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.upsert",
            new=AsyncMock(),
        ),
        patch(
            "src.cogs.workers.weekly_recap.job_post_db.get_posted_since",
            new=AsyncMock(return_value=posts),
        ),
    ):
        await cog.post_recaps(datetime.now(tz=timezone.utc))

    # Only the configured audience posts; the intern roles are not dumped there.
    assert set(sent) == {200}
    assert "Intern Role" not in sent[200]


async def test_recap_window_is_the_last_seven_days():
    config = GuildConfig(guild_id=1, forum_channel_id=1, grad_recap_channel_id=200)
    now = datetime.now(tz=timezone.utc)

    get_posted_since = AsyncMock(return_value=[])
    with (
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.get_all",
            new=AsyncMock(return_value=[config]),
        ),
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.upsert",
            new=AsyncMock(),
        ),
        patch(
            "src.cogs.workers.weekly_recap.job_post_db.get_posted_since",
            new=get_posted_since,
        ),
    ):
        await WeeklyRecap(MagicMock()).post_recaps(now)

    since = get_posted_since.call_args.args[1]
    assert abs((now - since) - timedelta(days=7)) < timedelta(seconds=1)


# The container runs in UTC and Sydney moves between UTC+10 and UTC+11, so the
# schedule is compared in the configured zone. A fixed UTC hour would drift an
# hour twice a year and stop being Friday evening.
def test_schedule_is_friday_evening_local_across_daylight_saving():
    from zoneinfo import ZoneInfo

    from src.config import RECAP_DAY, RECAP_HOUR, RECAP_TIMEZONE

    zone = ZoneInfo(RECAP_TIMEZONE)
    assert RECAP_DAY == 4  # Friday
    assert 17 <= RECAP_HOUR <= 21, "should be an evening hour"

    # One date in AEST (UTC+10) and one in AEDT (UTC+11).
    for moment in (
        datetime(2026, 8, 28, RECAP_HOUR, tzinfo=zone),
        datetime(2026, 12, 25, RECAP_HOUR, tzinfo=zone),
    ):
        as_utc = moment.astimezone(timezone.utc)
        back = as_utc.astimezone(zone)
        assert back.weekday() == RECAP_DAY
        assert back.hour == RECAP_HOUR


# python:*-slim has no system time zone database, so this depends on the tzdata
# package being installed. Without it ZoneInfo raises and the recap loop dies
# with no visible symptom other than recaps never arriving.
def test_recap_timezone_resolves():
    from src.cogs.workers.weekly_recap import RECAP_ZONE

    assert RECAP_ZONE.key == "Australia/Sydney"
    # And it must actually apply an offset, not silently degrade to UTC.
    assert datetime(2026, 12, 25, 12, tzinfo=RECAP_ZONE).utcoffset() != timedelta(0)


# The recap loop runs its first tick as soon as the cog loads, so restarting the
# bot inside the recap hour re-enters post_recaps. Sending twice is the exact
# noise the weekly recap exists to remove.
async def test_restart_inside_the_recap_hour_does_not_ping_twice():
    config = GuildConfig(
        guild_id=1, forum_channel_id=1, grad_recap_channel_id=200, grad_role_id=20
    )
    posts = [_post("Grad Role", "GRADUATE")]

    sends: list[str] = []

    def fake_channel(channel_id):
        channel = MagicMock()

        async def send(message, **kwargs):
            sends.append(message)

        channel.send = send
        return channel

    bot = MagicMock()
    bot.get_channel = fake_channel

    cog = WeeklyRecap(bot)
    now = datetime.now(tz=timezone.utc)
    with (
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.get_all",
            new=AsyncMock(return_value=[config]),
        ),
        patch("src.cogs.workers.weekly_recap.guild_config_db.upsert", new=AsyncMock()),
        patch(
            "src.cogs.workers.weekly_recap.job_post_db.get_posted_since",
            new=AsyncMock(return_value=posts),
        ),
    ):
        await cog.post_recaps(now)
        # Same hour, as a restart 20 minutes later would be.
        await cog.post_recaps(now + timedelta(minutes=20))

    assert len(sends) == 1


async def test_next_week_still_gets_a_recap():
    config = GuildConfig(
        guild_id=1, forum_channel_id=1, grad_recap_channel_id=200, grad_role_id=20
    )
    posts = [_post("Grad Role", "GRADUATE")]

    sends: list[str] = []

    def fake_channel(channel_id):
        channel = MagicMock()

        async def send(message, **kwargs):
            sends.append(message)

        channel.send = send
        return channel

    bot = MagicMock()
    bot.get_channel = fake_channel

    cog = WeeklyRecap(bot)
    now = datetime.now(tz=timezone.utc)
    with (
        patch(
            "src.cogs.workers.weekly_recap.guild_config_db.get_all",
            new=AsyncMock(return_value=[config]),
        ),
        patch("src.cogs.workers.weekly_recap.guild_config_db.upsert", new=AsyncMock()),
        patch(
            "src.cogs.workers.weekly_recap.job_post_db.get_posted_since",
            new=AsyncMock(return_value=posts),
        ),
    ):
        await cog.post_recaps(now)
        await cog.post_recaps(now + timedelta(days=7))

    assert len(sends) == 2
