from __future__ import annotations

import logging
from typing import Final

import discord

from src.backend.mongo.collections.col_jobs import JobDocument

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Ordered list of tags that every jobs forum channel should have.
ALL_TAG_NAMES: Final[list[str]] = [
    "Open",
    "Closed",
    "Intern/Student",
    "Graduate",
    "Professional",
    "Melbourne",
    "Sydney",
    "Other",
    "AU Citizen/PR",
    "NZ Citizen/PR",
    "International",
    "Other Rights",
]

# Unicode emoji for each fixed tag. Year tags are created without an emoji.
_TAG_EMOJI: Final[dict[str, str]] = {
    "Open": "🟢",
    "Closed": "🔴",
    "Intern/Student": "📚",
    "Graduate": "🎓",
    "Professional": "💼",
    "Melbourne": "☕",
    "Sydney": "🌉",
    "Other": "🌏",
    "AU Citizen/PR": "🇦🇺",
    "NZ Citizen/PR": "🇳🇿",
    "International": "🌐",
    "Other Rights": "🔑",
}

# Priority weight for non-status tags. Higher = kept first when trimming to the
# Discord 5-tag limit. Unknown/year tags default to 40 (above working rights).
TAG_WEIGHT: Final[dict[str, int]] = {
    "Intern/Student": 70,
    "Graduate": 70,
    "Professional": 70,
    "Melbourne": 60,
    "Sydney": 60,
    "Other": 50,
    "AU Citizen/PR": 30,
    "NZ Citizen/PR": 20,
    "International": 10,
    "Other Rights": 5,
}

_TYPE_TO_TAG: Final[dict[str, str]] = {
    "INTERN": "Intern/Student",
    "GRADUATE": "Graduate",
    "FULL_TIME": "Professional",
    "CONTRACT": "Professional",
    "PART_TIME": "Professional",
    "CASUAL": "Professional",
    "OTHER": "Professional",
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


def _job_year(job: JobDocument) -> int | None:
    dt = job.close_date or job.updated_at or job.created_at
    return dt.year if dt else None


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

    Ensures the fixed tag set plus a dynamic year tag derived from the job.
    """
    existing: dict[str, discord.ForumTag] = {t.name: t for t in channel.available_tags}

    for name in ALL_TAG_NAMES:
        await _ensure_tag(name, existing, channel, emoji=_TAG_EMOJI.get(name))

    year = _job_year(job)
    if year:
        await _ensure_tag(str(year), existing, channel)

    return existing


def apply_tag_limit(
    status_tag: discord.ForumTag,
    others: list[discord.ForumTag],
) -> list[discord.ForumTag]:
    """Return at most 5 tags with *status_tag* always first.

    The remaining 4 slots are filled by *others* sorted by TAG_WEIGHT descending.
    Tags not in TAG_WEIGHT (e.g. year tags) get a default weight of 40, placing
    them above working-rights tags but below location tags.
    """
    sorted_others = sorted(
        others, key=lambda t: TAG_WEIGHT.get(t.name, 40), reverse=True
    )
    return [status_tag] + sorted_others[:4]


def select_tags(
    job: JobDocument,
    tag_map: dict[str, discord.ForumTag],
) -> list[discord.ForumTag]:
    """Choose which tags to apply to a job's forum thread (max 5, Discord limit).

    - One type tag derived from job.type (e.g. Graduate, Intern/Student).
    - One or more location tags: Melbourne / Sydney / Other, based on job.locations.
      A job can earn multiple location tags (e.g. Melbourne + Sydney for multi-city roles).
      "Other" is applied for any location that is neither Melbourne nor Sydney.
    - Working rights tags (AU Citizen/PR, NZ Citizen/PR, International, Other Rights).
    - A year tag derived from close_date / updated_at / created_at.

    When candidates exceed 4, lower-weight tags are dropped first (see TAG_WEIGHT).
    The "Open" status tag always occupies slot 0.
    """
    open_tag = tag_map.get("Open")
    if open_tag is None:
        return []

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

    # Working rights tags
    for right in job.working_rights:
        tag = _RIGHTS_TO_TAG.get(right.upper())
        if tag:
            add(tag)

    # Year tag
    year = _job_year(job)
    if year:
        add(str(year))

    return apply_tag_limit(open_tag, others)
