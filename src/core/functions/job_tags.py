from __future__ import annotations

import logging
from typing import Final

import discord

from src.backend.mongo.collections.col_jobs import JobDocument

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Ordered list of tags that every jobs forum channel should have.
ALL_TAG_NAMES: Final[list[str]] = [
    "Intern/Student",
    "Graduate",
    "Junior (1-3 yoe)",
    "Experienced (4+ yoe)",
    "Melbourne",
    "Sydney",
    "Other",
]

# Unicode emoji for each fixed tag. Year tags are created without an emoji.
_TAG_EMOJI: Final[dict[str, str]] = {
    "Intern/Student": "📚",
    "Graduate": "🎓",
    "Junior (1-3 yoe)": "🌱",
    "Experienced (4+ yoe)": "💼",
    "Melbourne": "☕",
    "Sydney": "🌉",
    "Other": "🌏",
}

_TYPE_TO_TAG: Final[dict[str, str]] = {
    "INTERN": "Intern/Student",
    "GRADUATE": "Graduate",
    "FULL_TIME": "Experienced (4+ yoe)",
    "CONTRACT": "Experienced (4+ yoe)",
    "PART_TIME": "Junior (1-3 yoe)",
    "CASUAL": "Junior (1-3 yoe)",
}

# Australian state/territory codes that map to a city tag.
_LOCATION_TO_TAG: Final[dict[str, str]] = {
    "NSW": "Sydney",
    "VIC": "Melbourne",
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


def select_tags(
    job: JobDocument,
    tag_map: dict[str, discord.ForumTag],
) -> list[discord.ForumTag]:
    """Choose which tags to apply to a job's forum thread (max 5, Discord limit).

    - One type tag derived from job.type (e.g. Graduate, Intern/Student).
    - One or more location tags: Melbourne / Sydney / Other, based on job.locations.
      A job can earn multiple location tags (e.g. Melbourne + Sydney for multi-city roles).
      "Other" is applied for any location that is neither Melbourne nor Sydney.
    """
    selected: list[discord.ForumTag] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name not in seen and name in tag_map:
            selected.append(tag_map[name])
            seen.add(name)

    # Type-based tag
    if job.type:
        type_tag = _TYPE_TO_TAG.get(job.type)
        if type_tag:
            add(type_tag)

    # Location-based tags
    for loc in job.locations:
        add(_LOCATION_TO_TAG.get(loc.upper(), "Other"))

    # Year tag
    year = _job_year(job)
    if year:
        add(str(year))

    return selected[:5]
