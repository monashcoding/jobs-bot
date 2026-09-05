from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final

from src.backend.mongo.collections.col_jobs import job_col
from src.backend.sql.tables import job_post_db

_log: Final[logging.Logger] = logging.getLogger(__name__)


@dataclass
class BoardDiagnostics:
    """What the bot can actually see, counted at the source.

    Exists because "the filter is not working" and "the filter is working and
    the scraper is marking everything eligible" look identical from inside
    Discord, and so does "the bot is reading the wrong database". Each is a
    different fix, so the numbers have to come from Mongo rather than from
    reasoning about the forum.
    """

    database: str = ""
    total: int = 0
    eligible: int = 0
    ineligible: int = 0
    unscored: int = 0
    eligible_open: int = 0
    eligible_closed: int = 0
    eligible_outdated: int = 0
    records_this_guild: int = 0
    would_post: int = 0
    top_companies: list[tuple[str, int]] = field(default_factory=list)


async def collect_board_diagnostics(guild_id: int) -> BoardDiagnostics:
    """Count what is in active_jobs and what the board filter makes of it."""
    now = datetime.now(tz=timezone.utc)
    col = job_col._col()
    diag = BoardDiagnostics()

    try:
        diag.database = job_col.mongo._db.name
    except Exception:  # noqa: BLE001
        diag.database = "unknown"

    diag.total = await col.count_documents({})
    diag.eligible = await col.count_documents({"board_eligible": True})
    diag.ineligible = await col.count_documents({"board_eligible": False})
    # Missing entirely: never scored. Distinguished from an explicit false
    # because the fix differs -- one is the scraper not having run, the other is
    # the scraper deciding the role does not belong.
    diag.unscored = await col.count_documents({"board_eligible": {"$exists": False}})

    open_filter = {
        "board_eligible": True,
        "outdated": {"$ne": True},
        "$or": [{"close_date": None}, {"close_date": {"$gt": now}}],
    }
    diag.eligible_open = await col.count_documents(open_filter)
    diag.eligible_outdated = await col.count_documents(
        {"board_eligible": True, "outdated": True}
    )
    diag.eligible_closed = await col.count_documents(
        {
            "board_eligible": True,
            "outdated": {"$ne": True},
            "close_date": {"$ne": None, "$lte": now},
        }
    )

    posts = await job_post_db.get_by_guild(guild_id)
    diag.records_this_guild = len(posts)

    # What /jobs sync would create right now: postable jobs with no record yet.
    raw = await col.find(open_filter, {"_id": 1}).to_list(None)
    postable_ids = {str(d["_id"]) for d in raw}
    diag.would_post = len(postable_ids - {p.job_id for p in posts})

    # Several roles at one employer is normal; one employer dominating the
    # board is what "duplicate companies" usually turns out to be.
    diag.top_companies = await _top_companies(col, open_filter)

    return diag


async def _top_companies(col, open_filter: dict) -> list[tuple[str, int]]:
    """Return the most-represented companies among postable jobs."""
    try:
        cursor = col.aggregate(
            [
                {"$match": open_filter},
                {"$group": {"_id": "$company.name", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 5},
            ]
        )
        return [(doc["_id"] or "(unnamed)", doc["n"]) async for doc in cursor]
    except Exception:  # noqa: BLE001
        # Aggregation is a nicety; the counts above are the diagnosis.
        _log.exception("diagnose: company breakdown failed")
        return []
