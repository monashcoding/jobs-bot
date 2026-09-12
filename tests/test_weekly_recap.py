"""The weekly recap is now the only thing that pings.

Job posts used to mention a role on creation, which at scrape volume meant a
notification per job. The recap collects the week into one message per audience,
listing the employers whose threads drew the most conversation.
"""

from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import AsyncMock, MagicMock, patch

from src.backend.sql.models import DeadlineReminder, GuildConfig, JobPost
from src.cogs.workers.weekly_recap import (
    _MAX_LISTED,
    WeeklyRecap,
    audience_for,
    build_recap,
    company_entries,
    one_per_thread,
    role_mentions,
    thread_scores,
    threads_of,
)
from src.core.functions.job_post import GRAD_AUDIENCE, INTERN_AUDIENCE

_thread_ids = count(900)


def _post(
    title: str,
    job_type: str | None,
    guild_id: int = 1,
    company_name: str = "",
    company_tier: str | None = None,
    forum_post_id: int | None = None,
    close_date: datetime | None = None,
    outdated: bool = False,
    deadline_reminders_sent: list[str] | None = None,
    posted_at: datetime | None = None,
) -> JobPost:
    return JobPost(
        job_id=f"{title}:{company_name}:{forum_post_id}",
        guild_id=guild_id,
        # A thread of its own unless the caller is testing listings that share
        # one: the recap lists threads, so posts sharing an id collapse.
        forum_post_id=forum_post_id if forum_post_id is not None else next(_thread_ids),
        forum_channel_id=1,
        posted_at=posted_at or datetime.now(tz=timezone.utc),
        title=title,
        job_type=job_type,
        company_name=company_name,
        company_tier=company_tier,
        close_date=close_date,
        outdated=outdated,
        deadline_reminders_sent=deadline_reminders_sent or [],
    )


def _order(posts: list[JobPost], replies: dict[int, int] | None = None) -> list[str]:
    """The employers the recap would list, in the order it would list them."""
    entries = company_entries(threads_of(posts), thread_scores(posts, replies or {}))
    return [entry.name for entry in entries]


def test_audience_routing():
    assert audience_for("INTERN") == INTERN_AUDIENCE
    assert audience_for("GRADUATE") == GRAD_AUDIENCE
    assert audience_for("FULL_TIME") == GRAD_AUDIENCE
    # Unknown or missing type goes to the wider audience rather than vanishing.
    assert audience_for(None) == GRAD_AUDIENCE
    assert audience_for("SOMETHING_NEW") == GRAD_AUDIENCE


def test_build_recap_lists_companies_and_pings():
    posts = [
        _post("Backend Engineer", "INTERN", company_name="Canva"),
        _post("Data Intern", "INTERN", company_name="Optiver"),
    ]
    message = build_recap(posts, INTERN_AUDIENCE, "<@&42>", 555)

    assert "<@&42>" in message
    assert "2 new internship roles this week!" in message
    assert "Here are the most popular:" in message
    # The chip carries the employer: thread names lead with the company now.
    assert message.index("1. <#") < message.index("2. <#")
    assert _order(posts) == ["Canva", "Optiver"]
    # The list names employers now; the role title is not what people scan for.
    assert "Backend Engineer" not in message


def test_build_recap_singular():
    message = build_recap(
        [_post("Solo Role", "INTERN", company_name="Canva")],
        INTERN_AUDIENCE,
        "",
        555,
    )
    assert "1 new internship role this week!" in message


# A posting whose company the scraper did not name still has to render, so the
# role title stands in rather than leaving a blank line.
def test_a_nameless_company_falls_back_to_the_title():
    message = build_recap([_post("Solo Role", "GRADUATE")], GRAD_AUDIENCE, "", 555)
    assert "1. <#" in message


# Discord rejects messages over 2000 characters, and a busy week can exceed it.
def test_build_recap_stays_within_discord_limit():
    posts = [
        _post(f"Role {i}", "GRADUATE", company_name=f"Company Number {i}" * 3)
        for i in range(80)
    ]
    message = build_recap(posts, GRAD_AUDIENCE, "<@&1> <@&2>", 555)

    assert len(message) < 2000
    assert "80 new graduate roles" in message


# The recap is a prompt to open the board, not a copy of it.
def test_build_recap_lists_at_most_the_cap():
    posts = [
        _post(f"Role {i}", "GRADUATE", company_name=f"Company {i}") for i in range(30)
    ]
    message = build_recap(posts, GRAD_AUDIENCE, "", 555)

    assert message.count(". <#") == _MAX_LISTED
    assert "30 new graduate roles" in message


# The count is the only thing telling the reader the list is partial, so it has
# to survive both the entry cap and the character backstop.
def test_overflow_line_links_the_board_and_counts_the_rest():
    posts = [
        _post(f"Role {i}", "GRADUATE", company_name=f"Company {i}") for i in range(30)
    ]
    assert f"and {30 - _MAX_LISTED} more in <#555>." in build_recap(
        posts, GRAD_AUDIENCE, "", 555
    )

    # A heading long enough that the character budget, not the cap, ends the
    # list. The lines themselves are thread mentions and cannot grow, so the
    # backstop is now only reachable from above it -- but a guild with a wall
    # of notification roles is exactly what it is a backstop against.
    mentions = " ".join(
        f"<@&{n}>" for n in range(100000000000000000, 100000000000000077)
    )
    message = build_recap(posts, GRAD_AUDIENCE, mentions, 555)
    listed = message.count(". <#")
    assert listed < _MAX_LISTED
    assert f"and {30 - listed} more in <#555>." in message
    assert len(message) < 2000


def test_no_overflow_line_when_everything_fits():
    posts = [
        _post(f"Role {i}", "GRADUATE", company_name=f"Company {i}")
        for i in range(_MAX_LISTED)
    ]
    assert "more in <#" not in build_recap(posts, GRAD_AUDIENCE, "", 555)


# One employer, several roles: one line, and the count beside it is what says
# there is more than the thread being linked.
def test_a_company_hiring_twice_gets_one_line_and_a_count():
    posts = [
        _post("Role A", "GRADUATE", company_name="Canva", forum_post_id=1),
        _post("Role B", "GRADUATE", company_name="Canva", forum_post_id=2),
        _post("Role C", "GRADUATE", company_name="Optiver", forum_post_id=3),
    ]
    message = build_recap(posts, GRAD_AUDIENCE, "", 555, replies={2: 5})

    assert message.count(". <#") == 2
    assert "1. <#2> (2 roles)" in message
    assert "3 new graduate roles" in message
    # Nothing is left over: the two Canva roles are both accounted for by its
    # one line, so an "and N more" line would be counting them twice.
    assert "more in <#" not in message


def test_a_single_role_carries_no_count():
    message = build_recap(
        [_post("Role A", "GRADUATE", company_name="Canva")], GRAD_AUDIENCE, "", 555
    )
    assert "roles)" not in message


# The scraper spells one employer several ways, and three spellings of Google
# would otherwise take three of the ten slots.
def test_company_name_variants_collapse_to_one_entry():
    posts = [
        _post("Role A", "GRADUATE", company_name="Google", forum_post_id=1),
        _post(
            "Role B",
            "GRADUATE",
            company_name="Google Australia Pty Ltd",
            forum_post_id=2,
        ),
    ]
    message = build_recap(posts, GRAD_AUDIENCE, "", 555)

    assert message.count(". <#") == 1
    assert "(2 roles)" in message


# Every posting on the board already cleared the scraper's company gate, so the
# recap orders by prominence to decide which of them earn the visible slots.
def test_recap_orders_headline_companies_first():
    posts = [
        _post("Role A", "GRADUATE", company_name="A Co", company_tier="unranked"),
        _post("Role B", "GRADUATE", company_name="B Co", company_tier="major"),
        _post("Role C", "GRADUATE", company_name="C Co", company_tier="headline"),
    ]
    assert _order(posts) == ["C Co", "B Co", "A Co"]


# Documents written before the scraper emitted a tier still have to sort, so the
# recap falls back to the bot's own company list rather than dropping them all
# to the bottom together.
def test_recap_falls_back_to_the_company_list_when_untiered():
    posts = [
        _post("Role A", "GRADUATE", company_name="Some Unknown Startup"),
        _post("Role B", "GRADUATE", company_name="Deloitte"),
        _post("Role C", "GRADUATE", company_name="Atlassian"),
    ]
    assert _order(posts) == ["Atlassian", "Deloitte", "Some Unknown Startup"]


# A tiered and an untiered posting have to interleave correctly, or the week the
# scraper ships reads as two separate lists stapled together.
def test_tiered_and_untiered_postings_sort_together():
    posts = [
        _post("Untiered major", "GRADUATE", company_name="Deloitte"),
        _post(
            "Tiered headline",
            "GRADUATE",
            company_name="Tiered Co",
            company_tier="headline",
        ),
        _post("Untiered headline", "GRADUATE", company_name="Atlassian"),
        _post(
            "Tiered unranked",
            "GRADUATE",
            company_name="Unranked Co",
            company_tier="unranked",
        ),
    ]
    # Atlassian is one of the named draws, so it leads the headline tier ahead
    # of a company the scraper tiered but this bot has never heard of.
    assert _order(posts) == [
        "Atlassian",
        "Tiered Co",
        "Deloitte",
        "Unranked Co",
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
    assert _order(posts) == ["Some Unknown Startup", "Atlassian"]


# The headline tier is too coarse for a ten-line list on its own: Canva and a
# tier 1 bank would tie and break on posting order.
def test_the_biggest_draws_lead_their_tier():
    posts = [
        _post("Role A", "GRADUATE", company_name="Cochlear", company_tier="headline"),
        _post("Role B", "GRADUATE", company_name="Canva", company_tier="headline"),
        _post("Role C", "GRADUATE", company_name="Atlassian", company_tier="headline"),
    ]
    assert _order(posts) == ["Canva", "Atlassian", "Cochlear"]


def test_recap_order_is_stable_within_a_tier():
    posts = [
        _post("First", "GRADUATE", company_name="First Co", company_tier="headline"),
        _post("Second", "GRADUATE", company_name="Second Co", company_tier="headline"),
        _post("Third", "GRADUATE", company_name="Third Co", company_tier="headline"),
    ]
    assert _order(posts) == ["First Co", "Second Co", "Third Co"]


def test_headline_companies_win_the_visible_slots():
    posts = [
        _post(
            f"Filler {i}", "GRADUATE", company_name=f"Filler {i}", company_tier="major"
        )
        for i in range(20)
    ] + [
        _post(
            "The Good One", "GRADUATE", company_name="Good Co", company_tier="headline"
        )
    ]

    good = posts[-1]
    assert f"1. <#{good.forum_post_id}>" in build_recap(posts, GRAD_AUDIENCE, "", 555)


# A closing role draws messages whatever employer it is from -- the bot warns
# about the deadline and people answer it -- so engagement must never promote a
# company over a more prominent one. Being a name people open the message for is
# the whole reason the recap lists anybody.
def test_prominence_outranks_replies():
    quiet = _post("Quiet", "GRADUATE", company_name="Canva", company_tier="headline")
    busy = _post("Busy", "GRADUATE", company_name="Some Unknown Startup")

    assert _order([quiet, busy], {busy.forum_post_id: 40}) == [
        "Canva",
        "Some Unknown Startup",
    ]


# The named draws lead their tier too: they are the reason the order inside a
# tier exists at all.
def test_named_draws_lead_their_tier_however_quiet():
    named = _post("Quiet", "GRADUATE", company_name="Canva", company_tier="headline")
    busy = _post("Busy", "GRADUATE", company_name="Cochlear", company_tier="headline")

    assert _order([named, busy], {busy.forum_post_id: 40}) == ["Canva", "Cochlear"]


# Where prominence has nothing left to say, conversation decides.
def test_replies_order_equally_prominent_employers():
    a = _post("A", "GRADUATE", company_name="A Co", company_tier="major")
    b = _post("B", "GRADUATE", company_name="B Co", company_tier="major")

    assert _order([a, b], {}) == ["A Co", "B Co"]
    assert _order([a, b], {b.forum_post_id: 40}) == ["B Co", "A Co"]


# One person saying "applied, good luck" is not a thread worth leading the
# recap with. Two people talking is.
def test_a_single_reply_does_not_count_as_conversation():
    a = _post("A", "GRADUATE", company_name="A Co", company_tier="major")
    b = _post("B", "GRADUATE", company_name="B Co", company_tier="major")

    assert thread_scores([a, b], {b.forum_post_id: 1})[b.forum_post_id] == 0
    assert _order([a, b], {b.forum_post_id: 1}) == ["A Co", "B Co"]
    assert _order([a, b], {b.forum_post_id: 2}) == ["B Co", "A Co"]


# The count reaching the recap is of messages real people sent, so the bot's
# own warnings, Discord's rename notices and the deletion prompt are not in it
# and nothing has to be subtracted from it here.
def test_scores_are_taken_as_counted():
    closing = _post(
        "Closing",
        "GRADUATE",
        company_name="A Co",
        company_tier="major",
        close_date=datetime.now(tz=timezone.utc) + timedelta(days=1),
        deadline_reminders_sent=[
            DeadlineReminder.REMINDER_2W,
            DeadlineReminder.REMINDER_1W,
            DeadlineReminder.REMINDER_3D,
        ],
    )

    assert (
        thread_scores([closing], {closing.forum_post_id: 6})[closing.forum_post_id] == 6
    )


# A thread that has archived itself is missing from the active-thread listing
# the counts come from, and a recap that raised over that would not be sent.
def test_a_thread_with_no_reply_count_scores_zero():
    posts = [_post("Role A", "GRADUATE", company_name="Canva")]
    assert thread_scores(posts, {})[posts[0].forum_post_id] == 0
    assert ". <#" in build_recap(posts, GRAD_AUDIENCE, "", 555, replies={})


# A role that closed mid-week has had its apply buttons retired and its thread
# archived. Linking it spends one of ten slots on a dead end -- and closed
# threads are, if anything, the ones with the most replies.
def test_closed_roles_are_counted_but_not_listed():
    closed = _post(
        "Closed",
        "GRADUATE",
        company_name="Closed Co",
        close_date=datetime.now(tz=timezone.utc) - timedelta(days=2),
    )
    open_role = _post("Open", "GRADUATE", company_name="Open Co")

    message = build_recap(
        [closed, open_role], GRAD_AUDIENCE, "", 555, replies={closed.forum_post_id: 40}
    )

    # The heading is the week's volume, so it still counts both.
    assert "2 new graduate roles this week!" in message
    assert "Closed Co" not in message
    assert f"1. <#{open_role.forum_post_id}>" in message
    # And the closed one is not offered as "more" either.
    assert "more in <#" not in message


def test_an_outdated_listing_is_not_listed():
    posts = [_post("Gone", "GRADUATE", company_name="Gone Co", outdated=True)]
    message = build_recap(posts, GRAD_AUDIENCE, "", 555)

    assert "1 new graduate role this week!" in message
    assert "Gone Co" not in message
    # Nothing to list, but the board is still linked rather than named.
    assert "<#555>" in message


# One role advertised per city: Sydney closing does not close the role, and the
# thread is still worth linking.
def test_a_thread_open_in_one_city_is_still_listed():
    now = datetime.now(tz=timezone.utc)
    posts = [
        _post(
            "Delivery Consultant",
            "GRADUATE",
            company_name="Canva",
            forum_post_id=77,
            close_date=now - timedelta(days=1),
        ),
        _post(
            "Delivery Consultant",
            "GRADUATE",
            company_name="Canva",
            forum_post_id=77,
            close_date=now + timedelta(days=7),
        ),
    ]
    assert "1. <#77>" in build_recap(posts, GRAD_AUDIENCE, "", 555)


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
    intern, grad, professional = (
        _post("Intern Role", "INTERN"),
        _post("Grad Role", "GRADUATE"),
        _post("Professional Role", "FULL_TIME"),
    )
    posts = [intern, grad, professional]

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
    assert f"<#{intern.forum_post_id}>" in sent[100]
    assert "<@&10>" in sent[100]
    assert f"<#{grad.forum_post_id}>" in sent[200]
    assert f"<#{professional.forum_post_id}>" in sent[200]
    # An intern must not be pinged about graduate roles.
    assert f"<#{intern.forum_post_id}>" not in sent[200]
    assert "<@&20>" in sent[200]


async def test_audience_without_a_channel_is_skipped_not_misrouted():
    config = GuildConfig(
        guild_id=1, forum_channel_id=1, grad_recap_channel_id=200, grad_role_id=20
    )
    intern, grad = _post("Intern Role", "INTERN"), _post("Grad Role", "GRADUATE")
    posts = [intern, grad]

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
    assert f"<#{intern.forum_post_id}>" not in sent[200]
    assert f"<#{grad.forum_post_id}>" in sent[200]


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


def test_listings_sharing_a_thread_are_listed_once():
    # One role advertised in three states: three rows, one thread, one line in
    # the recap -- otherwise it names the same job three times and pushes two
    # other jobs off the end.
    posts = [
        _post(
            "Delivery Consultant", "GRADUATE", company_name="Canva", forum_post_id=77
        ),
        _post(
            "Delivery Consultant", "GRADUATE", company_name="Canva", forum_post_id=77
        ),
        _post(
            "Delivery Consultant", "GRADUATE", company_name="Canva", forum_post_id=77
        ),
        _post("Data Engineer", "GRADUATE", company_name="Optiver", forum_post_id=78),
    ]

    assert len(one_per_thread(posts)) == 2

    message = build_recap(posts, GRAD_AUDIENCE, "", 555)
    assert message.count(". <#") == 2
    assert "roles)" not in message
    assert "2 new graduate roles" in message
