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

_TYPE_TO_TAG: Final[dict[str, str]] = {
    "INTERNSHIP": "Intern/Student",
    "GRADUATE": "Graduate",
    "FULL_TIME": "Experienced (4+ yoe)",
    "CONTRACT": "Experienced (4+ yoe)",
    "PART_TIME": "Junior (1-3 yoe)",
    "CASUAL": "Junior (1-3 yoe)",
}


async def ensure_tags(
    channel: discord.ForumChannel,
) -> dict[str, discord.ForumTag]:
    """Return a name→tag mapping for all required tags, creating any that are missing.

    Missing tags are created via the Discord API. Tags that already exist are
    reused as-is — this is safe to call on every post without hammering the API
    once the channel is set up.
    """
    existing: dict[str, discord.ForumTag] = {t.name: t for t in channel.available_tags}

    for name in ALL_TAG_NAMES:
        if name in existing:
            continue
        try:
            tag = await channel.create_tag(name=name)
            existing[name] = tag
            _log.info("Created forum tag %r in channel %s", name, channel.id)
        except Exception:  # noqa: BLE001
            _log.exception(
                "Failed to create forum tag %r in channel %s — it will be skipped",
                name,
                channel.id,
            )

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
        loc_lower = loc.lower()
        if "melbourne" in loc_lower:
            add("Melbourne")
        elif "sydney" in loc_lower:
            add("Sydney")
        else:
            add("Other")

    return selected[:5]
