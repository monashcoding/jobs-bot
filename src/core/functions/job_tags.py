from __future__ import annotations

import logging
import re
from typing import Final

import discord

from src.backend.mongo.collections.col_jobs import JobDocument

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Tags this bot used to create and no longer does. Year tags ("2026") were once
# applied per posting; they duplicated the year already in the thread name, were
# identical across most of the board, and each new year permanently consumed one
# of a forum's 20 available tags.
#
# Matched by shape rather than by a list of names precisely so that a tag a team
# member added by hand is never caught by it: only a bare four-digit year is.
RETIRED_TAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(?:19|20)\d{2}$")

# Ordered list of tags that every jobs forum channel should have.
ALL_TAG_NAMES: Final[list[str]] = [
    "Open",
    "Closed",
    "Intern/Student",
    "Graduate",
    "Melbourne",
    "Sydney",
    "Other",
    "AU Citizen/PR",
    "NZ Citizen/PR",
    "International",
    "Anyone Can Apply",
    "Other Rights",
]

# Where each tag sits when a thread's tags are read left to right: status
# first, then what kind of role, then where it is, then who may apply. That is
# the order ALL_TAG_NAMES is already written in, so it is the source of it.
#
# Deliberately not TAG_WEIGHT. That decides which tag is dropped when a thread
# earns more than five, and the two questions have different answers: "Other"
# is the least useful tag on a thread and the first location to go, but while it
# is there it is still a location and belongs beside the other locations rather
# than after the working rights.
_DISPLAY_ORDER: Final[dict[str, int]] = {
    name: position for position, name in enumerate(ALL_TAG_NAMES)
}

# A tag this bot does not apply -- one added to a thread or a forum by hand --
# sorts after every tag it does, rather than in among them.
_UNORDERED: Final[int] = len(ALL_TAG_NAMES)


def display_position(name: str) -> int:
    """Return where a tag named *name* sorts in a thread's tag list."""
    return _DISPLAY_ORDER.get(name, _UNORDERED)


def in_display_order(tags: list[discord.ForumTag]) -> list[discord.ForumTag]:
    """Return *tags* in the order a reader should meet them.

    Sorted rather than filtered: a tag this bot knows nothing about keeps its
    place at the end instead of being dropped, because a team member put it
    there on purpose.
    """
    return sorted(tags, key=lambda tag: display_position(tag.name))


# Unicode emoji for each tag.
_TAG_EMOJI: Final[dict[str, str]] = {
    "Open": "🟢",
    "Closed": "🔴",
    "Intern/Student": "📚",
    "Graduate": "🎓",
    "Melbourne": "☕",
    "Sydney": "🌉",
    "Other": "🌏",
    "AU Citizen/PR": "🇦🇺",
    "NZ Citizen/PR": "🇳🇿",
    "International": "🌐",
    "Anyone Can Apply": "🔓",
    "Other Rights": "🔑",
}

# Priority weight for non-status tags. Higher = kept first when trimming to the
# Discord 5-tag limit. Anything not listed here -- a tag added to a thread by
# hand, or one this bot no longer applies -- defaults to 40 and is dropped
# before the tags below it.
#
# The order says: what kind of role, then which city, then who may apply, then
# the vaguer versions of the last two.
#
# "Other" as a location once outranked every working-rights tag, which meant a
# role hiring in three or more states lost its rights tags to it. Five listings
# on the board were in exactly that shape -- EY and CommBank programs across
# five states -- and each spent a slot saying "also somewhere else" in place of
# the tag naming who could apply. A location tag that does not name the location
# is the least useful thing on the thread, so it now sorts below the rights.
TAG_WEIGHT: Final[dict[str, int]] = {
    "Intern/Student": 70,
    "Graduate": 70,
    "Melbourne": 60,
    "Sydney": 60,
    "Anyone Can Apply": 55,
    "International": 54,
    "AU Citizen/PR": 52,
    "NZ Citizen/PR": 50,
    "Other": 45,
    "Other Rights": 42,
}

# The scraper's JobType enum, in full: EOI, PRE_PENULTIMATE, INTERN, GRADUATE,
# OTHER. EOI listings are dropped before they are stored and PRE_PENULTIMATE
# never survives normalisation, so only the last three ever reach a document.
#
# OTHER is absent, and so is the Professional tag it used to earn. The board is
# for students, and the scraper's board gate admits only INTERN and GRADUATE, so
# no OTHER listing reaches a thread to be tagged. It was briefly admitted and
# then rejected on the proportion: the board came out 19 intern, 21 graduate and
# 60 professional, which is not a board for students.
#
# This table also used to carry FULL_TIME, CONTRACT, PART_TIME and CASUAL, none
# of which is a value the scraper can produce.
_TYPE_TO_TAG: Final[dict[str, str]] = {
    "INTERN": "Intern/Student",
    "GRADUATE": "Graduate",
}

# Australian state/territory codes that map to a city tag.
_LOCATION_TO_TAG: Final[dict[str, str]] = {
    "NSW": "Sydney",
    "VIC": "Melbourne",
}

_RIGHTS_TO_TAG: Final[dict[str, str]] = {
    "AUS_CITIZEN_PR": "AU Citizen/PR",
    "NZ_CITIZEN_PR": "NZ Citizen/PR",
    "INTERNATIONAL": "International",
    "OTHER_RIGHTS": "Other Rights",
}

# The tag for a listing that accepts citizens and international applicants
# alike. One tag rather than the two it replaces, and a plainer sentence than
# either: a reader does not have to work out that two tags side by side mean
# there is no restriction. Rename here and the forum follows on the next post.
_ANY_RIGHTS_TAG: Final[str] = "Anyone Can Apply"

# The rights a listing must carry to earn it.
_ANY_RIGHTS_REQUIRES: Final[frozenset[str]] = frozenset(
    {"INTERNATIONAL", "AUS_CITIZEN_PR"}
)


def _rights_tags(working_rights: list[str]) -> list[str]:
    """Return the working-rights tag names for *working_rights*.

    A listing that accepts both citizens and international applicants is not
    restricted at all, and every such listing on the board says so by ticking
    all four rights at once. Tagging all four spends every remaining slot
    restating one fact, and since a thread holds five tags the lowest-weighted
    of them was dropped -- which was International, the one a reader needed.
    It never appeared on the board at all.

    So that combination collapses to a single tag saying the plain thing, and
    the specific tags survive only where they carry information: a listing open
    to citizens but not internationals, where AU versus NZ is the whole point.
    """
    names = {r.upper() for r in working_rights}
    if _ANY_RIGHTS_REQUIRES <= names:
        return [_ANY_RIGHTS_TAG]

    return [_RIGHTS_TO_TAG[name] for name in sorted(names) if name in _RIGHTS_TO_TAG]


async def _ensure_tag(
    name: str,
    existing: dict[str, discord.ForumTag],
    channel: discord.ForumChannel,
    emoji: str | None = None,
) -> None:
    if name in existing:
        return
    try:
        existing[name] = await channel.create_tag(
            name=name,
            emoji=discord.PartialEmoji(name=emoji) if emoji else None,
            moderated=True,
        )
        _log.info("Created forum tag %r in channel %s", name, channel.id)
    except Exception:  # noqa: BLE001
        _log.exception(
            "Failed to create forum tag %r in channel %s; it will be skipped",
            name,
            channel.id,
        )


async def ensure_tags(
    channel: discord.ForumChannel,
    job: JobDocument,
) -> dict[str, discord.ForumTag]:
    """Return a name->tag mapping for all required tags, creating any that are missing.

    *job* is unused and kept for the call sites: tags were once derived from the
    document (a year tag per posting), and the signature is left able to do that
    again rather than being churned back and forth.
    """
    existing: dict[str, discord.ForumTag] = {t.name: t for t in channel.available_tags}

    for name in ALL_TAG_NAMES:
        await _ensure_tag(name, existing, channel, emoji=_TAG_EMOJI.get(name))

    return existing


def apply_tag_limit(
    status_tag: discord.ForumTag,
    others: list[discord.ForumTag],
) -> list[discord.ForumTag]:
    """Return at most 5 tags with *status_tag* always first.

    Which tags survive and what order they are shown in are separate questions,
    answered separately. The remaining 4 slots are filled by *others* by
    TAG_WEIGHT descending -- a tag not in TAG_WEIGHT gets a default weight of
    40, below every tag this bot applies, so an unrecognised one is the first to
    go -- and what survives is then put in reading order (see _DISPLAY_ORDER),
    so every thread on the board is tagged in the same sequence.
    """
    sorted_others = sorted(
        others, key=lambda t: TAG_WEIGHT.get(t.name, 40), reverse=True
    )
    return [status_tag] + in_display_order(sorted_others[:4])


def _candidate_tags(
    job: JobDocument,
    tag_map: dict[str, discord.ForumTag],
) -> list[discord.ForumTag]:
    """Return every non-status tag *job* earns, before the 5-tag limit is applied.

    - One type tag derived from job.type (e.g. Graduate, Intern/Student).
    - One or more location tags: Melbourne / Sydney / Other, based on job.locations.
      A job can earn multiple location tags (e.g. Melbourne + Sydney for multi-city roles).
      "Other" is applied for any location that is neither Melbourne nor Sydney.
    - Working rights tags, collapsed to one where possible (see _rights_tags).

    No year tag. The thread name already carries the year ("{title} | {company}
    [{year}]"), every listing on the board tends to share the same one, and each
    new year permanently consumes one of the forum's 20 available tags. It spent
    a slot on the one thing a reader could already see.
    """
    seen: set[str] = set()
    others: list[discord.ForumTag] = []

    def add(name: str) -> None:
        if name not in seen and name in tag_map:
            others.append(tag_map[name])
            seen.add(name)

    # Type-based tag
    if job.type:
        type_tag = _TYPE_TO_TAG.get(job.type)
        if type_tag:
            add(type_tag)

    # Location-based tags
    for loc in job.locations:
        add(_LOCATION_TO_TAG.get(loc.upper(), "Other"))

    # Working rights tags, collapsed to one where possible (see _rights_tags).
    for name in _rights_tags(job.working_rights):
        add(name)

    return others


def select_tags(
    job: JobDocument,
    tag_map: dict[str, discord.ForumTag],
) -> list[discord.ForumTag]:
    """Choose which tags to apply to a job's forum thread (max 5, Discord limit).

    When candidates exceed 4, lower-weight tags are dropped first (see TAG_WEIGHT).
    The "Open" status tag always occupies slot 0.
    """
    open_tag = tag_map.get("Open")
    if open_tag is None:
        return []

    return select_tags_for_status(job, tag_map, open_tag)


def select_tags_for_status(
    job: JobDocument,
    tag_map: dict[str, discord.ForumTag],
    status_tag: discord.ForumTag,
) -> list[discord.ForumTag]:
    """The tags *job* earns, under a status tag chosen by the caller.

    Open/Closed is not derivable from the document alone -- a job can be closed
    because its deadline passed, because it went outdated, or because it stopped
    being board material -- so the one caller that knows which it is (the
    /fix-tags reconciliation) passes it in rather than having it guessed here.
    """
    return apply_tag_limit(status_tag, _candidate_tags(job, tag_map))


def resync_tags(
    job: JobDocument,
    tag_map: dict[str, discord.ForumTag],
    current: list[discord.ForumTag],
) -> list[discord.ForumTag] | None:
    """Return the tags a live thread should carry, or None if it already has them.

    Threads are tagged once, at post time, and the scraper keeps revising the
    document behind them: a role gains a second city, its working rights are
    re-parsed. Nothing re-reads those tags, so a thread's tags are a snapshot of
    what the job looked like the day it was posted and drift from it forever
    after. This also retires tags the bot has stopped applying, since a tag the
    job no longer earns is simply absent from the recomputed set.

    Two things are deliberately preserved rather than recomputed.

    The status tag is taken from *current*, not from the job: the deadline
    watcher owns Open/Closed, and recomputing it here would reopen every closed
    thread the moment its job document was touched. A thread with no status tag
    at all falls back to Open, which is what a live thread should carry.

    Returning None for an unchanged thread is the point of the function, not an
    optimisation. This runs on every update event for every guild, and an edit
    that changes nothing still spends a request against the rate limit that the
    thread which does need fixing is queued behind.
    """
    by_name = {t.name: t for t in current}
    status = by_name.get("Closed") or by_name.get("Open") or tag_map.get("Open")
    if status is None:
        return None

    desired = select_tags_for_status(job, tag_map, status)
    if {t.name for t in desired} == set(by_name):
        return None

    return desired


def channel_tags_in_order(
    tags: list[discord.ForumTag],
) -> list[discord.ForumTag]:
    """Return a forum's own tag list in reading order.

    Discord draws a thread's tags, and the forum's filter bar, in the order the
    *channel* lists its tags -- not the order a thread applied them. So the
    order on the channel is the one a reader actually sees, and a forum whose
    tags were created in some other order shows every thread in that order
    however carefully each thread was tagged.

    Tags the bot does not know about keep their relative order at the end. Only
    the sequence changes: these are the same tag objects, so no thread loses a
    tag over a reordering.
    """
    return in_display_order(tags)
