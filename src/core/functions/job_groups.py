"""One role, several listings.

LinkedIn splits a role hiring in three states into three postings, each with its
own job id, its own deadline and its own apply link. Upstream they are genuinely
distinct listings, so nothing in the scraper collapses them and three documents
reach the collection.

The board is a curated surface and three threads for one role reads as the bot
duplicating jobs, so the listings are grouped here into one thread carrying an
apply link per city. The website keeps the duplicates, deliberately: it has the
volume to absorb them and the per-city pages are what the links point at.

Everything in this module works on the group, so the rest of the bot can ask a
plain question -- which listings share this thread, which of them are still
live, what should the buttons say -- without repeating the merge rules.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Final

from src.backend.mongo.collections.col_jobs import JobDocument
from src.backend.sql.models import JobPost
from src.core.functions.job_eligibility import is_post_open

_log: Final[logging.Logger] = logging.getLogger(__name__)

# How a location code reads on a button. Anything not listed falls through as
# its own code, which is what the states already are.
_LOCATION_LABEL: Final[dict[str, str]] = {
    "AUSTRALIA": "Australia",
    "REMOTE": "Remote",
}

# Discord truncates a button label past 80 characters.
_MAX_LABEL: Final[int] = 80


def group_key(company_name: str, title: str) -> tuple[str, str]:
    """The key two listings must share to be treated as one role.

    Company and title, matched exactly. Deliberately conservative: it catches
    every duplicate on the board, while two roles that differ in any visible way
    stay apart. BCG runs a "Forward Deployed AI Scientist" and a "Forward
    Deployed AI Engineer" graduate program at once, and merging those would hide
    a real opening rather than a duplicate of one.
    """
    return (company_name.strip(), title.strip())


def group_jobs(jobs: Sequence[JobDocument]) -> list[list[JobDocument]]:
    """Group *jobs* by role, preserving the order they arrived in.

    The first member of each group is its primary: the thread is named after it,
    carries its embed, and is keyed on its id. Callers pass jobs sorted oldest
    first, so the primary is the listing that has been around longest -- the one
    most likely to already have a thread, and the least likely to disappear
    before its siblings do.
    """
    groups: dict[tuple[str, str], list[JobDocument]] = {}
    for job in jobs:
        groups.setdefault(group_key(job.company.name, job.title), []).append(job)
    return list(groups.values())


def merge_documents(jobs: Sequence[JobDocument]) -> JobDocument:
    """Return the primary of *jobs* widened by what its siblings know.

    Only the fields that describe reach are merged. Locations are the point --
    a role split three ways holds one state each, and the union is the role as
    it is actually advertised -- and working rights come with them because a
    per-city posting can be parsed differently from its siblings.

    Nothing else is merged. Deadlines stay per listing (each city closes on its
    own date, which is why the thread tracks them separately), and the prose is
    the primary's, because three near-identical descriptions merged into one
    would read worse than either.
    """
    if not jobs:
        raise ValueError("merge_documents requires at least one job")

    primary = jobs[0]
    if len(jobs) == 1:
        return primary

    merged = primary.model_copy(deep=True)
    merged.locations = _ordered_union(job.locations for job in jobs)
    merged.working_rights = _ordered_union(job.working_rights for job in jobs)
    return merged


def widen_to_thread(job: JobDocument, posts: Sequence[JobPost]) -> JobDocument:
    """Return *job* widened by the other listings sharing its thread.

    Tags describe the thread, and the thread is the role: a reader filtering the
    forum for Melbourne should find a role hiring in Melbourne and Sydney,
    whichever of the two listings the scraper happened to touch last.

    The listings are SQL rows rather than documents because that is what the
    thread knows about itself. They carry the same locations and rights fields,
    denormalised at post time and kept in sync on every update, so the union is
    the same one merge_documents would produce from the documents.
    """
    others = [post for post in posts if post.job_id != job.id]
    if not others:
        return job

    widened = job.model_copy(deep=True)
    widened.locations = _ordered_union(
        [job.locations, *(post.locations for post in others)]
    )
    widened.working_rights = _ordered_union(
        [job.working_rights, *(post.working_rights for post in others)]
    )
    return widened


def _ordered_union(values: Iterable[Sequence[str]]) -> list[str]:
    """Flatten *values* into one list, first occurrence wins, order preserved."""
    seen: dict[str, None] = {}
    for group in values:
        for value in group:
            seen.setdefault(value, None)
    return list(seen)


def apply_label(locations: Sequence[str]) -> str:
    """The label for one listing's apply button.

    Named by where the role is, because that is the only thing separating the
    buttons: a reader picks the city they can work in. A listing with no
    location at all still gets a button, since a link nobody can find is worse
    than a vaguely labelled one.
    """
    if not locations:
        return "Apply Now"

    places = " / ".join(
        _LOCATION_LABEL.get(loc.upper(), loc.upper()) for loc in locations
    )
    return f"Apply — {places}"[:_MAX_LABEL]


def apply_labels(listings: Sequence[Sequence[str]]) -> list[str]:
    """Labels for a whole group's buttons, disambiguated where they collide.

    Two listings for the same role in the same city do happen -- an employer
    posting twice by mistake -- and two buttons reading "Apply — NSW" give a
    reader no way to tell them apart, so the repeats are numbered.
    """
    labels = [apply_label(locations) for locations in listings]
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1

    seen: dict[str, int] = {}
    out: list[str] = []
    for label in labels:
        if counts[label] == 1:
            out.append(label)
            continue
        seen[label] = seen.get(label, 0) + 1
        out.append(f"{label} ({seen[label]})"[:_MAX_LABEL])
    return out


def primary_post(posts: Sequence[JobPost]) -> JobPost:
    """The post that owns the thread: the one it was created for.

    Oldest first by posting time, with the job id breaking a tie so that two
    listings posted in the same batch always resolve the same way. The thread's
    name and embed follow this one, so it has to be stable across restarts and
    across the several places that need to know it.
    """
    return min(posts, key=lambda p: (p.posted_at, p.job_id))


def live_posts(posts: Sequence[JobPost]) -> list[JobPost]:
    """The listings on a thread that can still be applied to."""
    return [post for post in posts if is_post_open(post)]
