from __future__ import annotations

import logging
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
