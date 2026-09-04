from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Final

from src.backend.mongo.collections.col_jobs import JobDocument, job_col

_log: Final[logging.Logger] = logging.getLogger(__name__)


def is_board_eligible(job: JobDocument) -> bool:
    """Return True if *job* should get a forum thread.

    The scraper classifies every listing and sets ``board_eligible`` to say
    whether the role belongs on the job board; the collection holds every job
    scraped, not just the ones worth posting.

    This is deliberately default-deny. A job whose ``board_eligible`` is missing
    has not been scored -- the scraper's AI parser and board scoring steps have
    not run over it -- and posting unscored jobs means posting the entire
    collection. Discord caps a forum at 1000 active threads, which the active
    job count alone can exceed, so an unscored job is skipped and logged rather
    than posted on the assumption that it is wanted.
    """
    if job.board_eligible is None:
        _log.warning(
            "Job %r (%s) has no board_eligible field; skipping. The scraper's "
            "AI_Parser and BoardScoring steps must run before jobs can post.",
            job.title,
            job.company.name,
        )
        return False

    return job.board_eligible


def is_open_for_applications(job: JobDocument, now: datetime | None = None) -> bool:
    """Return True unless *job* has already closed.

    A thread for a role nobody can apply to is noise twice over: it is posted,
    and then the deadline watcher immediately renames it, tags it Closed and
    archives it. The board ends up advertising dead listings and the forum
    churns for nothing.

    Unlike ``board_eligible`` this is default-*allow*, and the asymmetry is
    deliberate. A missing ``board_eligible`` means the job was never scored, so
    nothing is known about it. A missing ``close_date`` means something
    different and much more ordinary: plenty of real listings carry no deadline
    at all, and rolling applications are common. Refusing those would empty the
    board of perfectly applicable roles, so only a deadline that has actually
    passed counts as closed.
    """
    if job.outdated:
        _log.debug(
            "Job %r (%s) is marked outdated; not posting",
            job.title,
            job.company.name,
        )
        return False

    if job.close_date is None:
        return True

    now = now or datetime.now(tz=timezone.utc)

    # Documents are read with tz_aware=True, so close_date is normally aware.
    # A naive value would raise on comparison, and taking down the watcher over
    # one malformed date is worse than posting one stale job.
    close_date = job.close_date
    if close_date.tzinfo is None:
        close_date = close_date.replace(tzinfo=timezone.utc)

    if close_date <= now:
        _log.debug(
            "Job %r (%s) closed at %s; not posting",
            job.title,
            job.company.name,
            close_date,
        )
        return False

    return True


async def fetch_board_eligible_ids() -> set[str]:
    """Return the ids of every board-eligible job, as strings.

    For the reconciliation commands, which work from JobPost records. Those
    records do not carry ``board_eligible`` -- it lives on the Mongo document --
    so a command that reopens or re-tags existing threads has to ask for it, or
    it will happily resurrect threads the board filter exists to keep out.

    Projected to ids only: this answers a set-membership question over the whole
    collection, and the documents themselves are not wanted.
    """
    raw = await job_col._col().find({"board_eligible": True}, {"_id": 1}).to_list(None)
    return {str(doc["_id"]) for doc in raw}
