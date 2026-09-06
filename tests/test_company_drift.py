"""The drift check between the scraper's company tiers and this bot's fallback.

The scraper owns the list and lives in another repository, so nothing here can
assert the two are in step. What is testable is the parser: if it silently read
the wrong strings, the check would report "no drift" forever and the fallback
would rot unnoticed for the one release it is alive.
"""

import os
from pathlib import Path

import pytest

from scripts.check_company_drift import scraper_company_tiers
from src.core.functions.company_rank import local_tiers, normalise_company

_GO_SOURCE = """
package utils

// "Not A Company" appears in a doc comment above the list.
var notableCompanies = map[string]bool{}

var headlineCompanyNames = []string{
	// --- Big tech ---
	"Google", "Amazon Web Services", "AWS",
	// "Retired Corp" was removed.
	"Optiver",
}

var majorCompanyNames = []string{
	"Deloitte", "Vocus",
	// A name in both slices ranks by the better of the two.
	"Google",
}

var somethingElse = []string{"Unrelated Literal"}
"""


def test_parser_reads_both_tiers_and_only_the_lists():
    tiers = scraper_company_tiers(_GO_SOURCE)

    assert tiers == {
        "Google": "headline",
        "Amazon Web Services": "headline",
        "AWS": "headline",
        "Optiver": "headline",
        "Deloitte": "major",
        "Vocus": "major",
    }
    # Literals from the doc comment, a commented-out entry, and an unrelated
    # slice further down the file all stay out.
    assert "Not A Company" not in tiers
    assert "Retired Corp" not in tiers
    assert "Unrelated Literal" not in tiers


# The scraper's own init() lets the first tier to claim a name keep it, and the
# comparison has to agree or every dual-listed company reads as a mismatch.
def test_a_name_in_both_slices_keeps_the_better_tier():
    assert scraper_company_tiers(_GO_SOURCE)["Google"] == "headline"


def test_parser_rejects_a_file_without_the_lists():
    with pytest.raises(SystemExit):
        scraper_company_tiers("package utils\n\nfunc main() {}\n")


# Runs only where the scraper checkout is available -- CI in this repository
# does not have it, but a developer with both repositories, or the scraper's own
# CI, gets the real comparison.
@pytest.mark.skipif(
    not os.environ.get("JOBS_SCRAPER_COMPANIES"),
    reason="JOBS_SCRAPER_COMPANIES not set; no scraper checkout to compare against",
)
def test_no_drift_against_the_scraper():
    source = Path(os.environ["JOBS_SCRAPER_COMPANIES"]).expanduser().read_text()
    board = {
        key: tier
        for name, tier in scraper_company_tiers(source).items()
        if (key := normalise_company(name))
    }
    local = local_tiers()

    untiered = sorted(board.keys() - local.keys())
    assert not untiered, (
        f"{len(untiered)} companies the scraper tiers have no tier here, so they "
        f"rank last through the fallback: {untiered}"
    )

    mismatched = {
        key: (board[key], local[key])
        for key in board.keys() & local.keys()
        if board[key] != local[key]
    }
    assert not mismatched, f"tiered differently on each side: {mismatched}"
