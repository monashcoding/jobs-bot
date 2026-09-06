#!/usr/bin/env python3
"""Report drift between the scraper's company tiers and this bot's fallback copy.

The scraper owns the company list and now emits a `company_tier` on every
document it scores. This bot keeps a tiered copy of the same names in
company_rank.py, used only as a fallback for documents written before that.
Nothing keeps the two in step, so this compares them.

The three differences it reports:

  Untiered    A company the scraper lists that has no tier here. Reached only
              through the fallback, so it matters only while documents the
              scraper has not tiered still exist -- but while they do, such a
              company ranks below every named employer and never wins a recap
              slot.

  Mismatched  A company both sides tier differently. Same blast radius: it shows
              only through the fallback, and only until the scraper's backfill
              has run over everything.

  Stale       A company tiered here that the scraper no longer lists. Harmless
              -- it simply never matches -- but worth pruning.

Untiered and mismatched set the exit code; stale is reported only.

**This is scaffolding with a known end date.** It exists for the single release
in which the fallback in company_rank.py is alive. Once no document the recap can
reach is missing a tier -- `/jobs diagnostics` reports that count -- the fallback
goes and this goes with it. See COMPANY-TIER-PLAN.md.

Usage:
    scripts/check_company_drift.py path/to/scraper/internal/utils/notable_companies.go
    JOBS_SCRAPER_COMPANIES=path/to/notable_companies.go scripts/check_company_drift.py

Exits 1 on untiered or mismatched companies, so it can gate CI in the scraper's
repository, where the list actually changes.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.functions.company_rank import (
    TIER_HEADLINE,
    TIER_MAJOR,
    local_tiers,
    normalise_company,
)

# The Go source declares one slice per tier:
#     var headlineCompanyNames = []string{...}
#     var majorCompanyNames = []string{...}
# Each is read separately so the tier a name sits in is known, not merely that it
# is on the list. Reading only these blocks keeps unrelated string literals --
# including the ones in the doc comments above them -- out of the comparison.
_BLOCK_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    TIER_HEADLINE: re.compile(
        r"headlineCompanyNames\s*=\s*\[\]string\{(.*?)\n\}", re.DOTALL
    ),
    TIER_MAJOR: re.compile(r"majorCompanyNames\s*=\s*\[\]string\{(.*?)\n\}", re.DOTALL),
}

_STRING_PATTERN: Final[re.Pattern[str]] = re.compile(r'"([^"]*)"')

# Go's own comment markers inside a block, stripped before scanning for literals
# so a commented-out entry is not counted as live.
_COMMENT_PATTERN: Final[re.Pattern[str]] = re.compile(r"//[^\n]*")


def scraper_company_tiers(source: str) -> dict[str, str]:
    """Extract the scraper's company-name-to-tier mapping from its Go source.

    Keys are original spellings, not normalised, so a report can name a company
    the way the scraper does.
    """
    found: dict[str, str] = {}
    for tier, pattern in _BLOCK_PATTERNS.items():
        block = pattern.search(source)
        if block is None:
            raise SystemExit(
                f"Could not find `{tier}CompanyNames = []string{{...}}` in that "
                "file. Point this at the scraper's notable_companies.go."
            )
        for name in _STRING_PATTERN.findall(_COMMENT_PATTERN.sub("", block.group(1))):
            # First tier to claim a name keeps it, matching the scraper's own
            # init() and this bot's tier tables.
            found.setdefault(name, tier)
    return found


def main() -> int:
    argument = (
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("JOBS_SCRAPER_COMPANIES")
    )
    if not argument:
        raise SystemExit(
            "Give the path to the scraper's notable_companies.go, either as an "
            "argument or in JOBS_SCRAPER_COMPANIES."
        )

    path = Path(argument).expanduser()
    if not path.is_file():
        raise SystemExit(f"No such file: {path}")

    # One original spelling per key, so the report reads the way the scraper's
    # own source does rather than in normalised form.
    board: dict[str, tuple[str, str]] = {}
    for name, tier in scraper_company_tiers(path.read_text()).items():
        if key := normalise_company(name):
            board.setdefault(key, (name, tier))

    local = local_tiers()

    untiered = sorted(board[key][0] for key in board.keys() - local.keys())
    stale = sorted(local.keys() - board.keys())
    mismatched = sorted(
        (board[key][0], board[key][1], local[key])
        for key in board.keys() & local.keys()
        if board[key][1] != local[key]
    )

    print(f"Scraper tiers {len(board)} companies; {len(local)} are tiered here.")

    if untiered:
        print(
            f"\n{len(untiered)} tiered by the scraper with no tier here "
            "(ranks last through the fallback):"
        )
        for name in untiered:
            print(f"  {name}")

    if mismatched:
        print(f"\n{len(mismatched)} tiered differently on each side:")
        for name, theirs, ours in mismatched:
            print(f"  {name}: scraper says {theirs}, this repo says {ours}")

    if stale:
        print(f"\n{len(stale)} tiered here but no longer listed (prunable):")
        for key in stale:
            print(f"  {key}")

    if not untiered and not mismatched and not stale:
        print("\nNo drift.")

    return 1 if untiered or mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
