"""Company prominence ranking, which decides what a recap shows first.

The scraper's notable-company list decides what reaches the board at all. It is
a flat gate, so it cannot order what it lets through -- these tiers do.
"""

from src.core.functions.company_rank import (
    HEADLINE_RANK,
    MAJOR_RANK,
    TIER_HEADLINE,
    TIER_MAJOR,
    TIER_UNRANKED,
    UNRANKED_RANK,
    company_rank,
    local_tiers,
    normalise_company,
    rank_for,
)


# Sources spell one employer many ways, so matching the raw string misses most
# of them.
def test_normalisation_collapses_spellings():
    assert normalise_company("Amazon Web Services (AWS)") == "amazonwebservices"
    assert normalise_company("Amazon AU") == "amazon"
    assert normalise_company("Google Australia Pty Ltd") == "google"
    assert normalise_company("J.P. Morgan") == "jpmorgan"
    assert normalise_company("  atlassian  ") == "atlassian"


def test_tiers():
    assert company_rank("Atlassian") == HEADLINE_RANK
    assert company_rank("Jane Street") == HEADLINE_RANK
    assert company_rank("Commonwealth Bank of Australia") == HEADLINE_RANK
    assert company_rank("Deloitte") == MAJOR_RANK
    assert company_rank("Vocus") == MAJOR_RANK


# An employer the board carries but this file does not list still gets posted;
# it just does not win a visible slot over a name people recognise.
def test_unknown_and_missing_sort_last():
    assert company_rank("Some Unknown Startup") == UNRANKED_RANK
    assert company_rank("") == UNRANKED_RANK
    assert company_rank(None) == UNRANKED_RANK


# A name in both blocks ranks by the better of the two.
def test_duplicate_across_tiers_keeps_the_better_rank():
    assert company_rank("Netflix") == HEADLINE_RANK


# The scraper owns the company list, so its tier is authoritative wherever it
# exists. The tables in this file are only a fallback until it emits one for
# every document; see COMPANY-TIER-PLAN.md.
def test_the_scrapers_tier_wins_over_the_local_list():
    assert rank_for(TIER_MAJOR, "Atlassian") == MAJOR_RANK
    assert rank_for(TIER_HEADLINE, "Some Unknown Startup") == HEADLINE_RANK
    assert rank_for(TIER_UNRANKED, "Google") == UNRANKED_RANK


def test_missing_tier_falls_back_to_the_local_list():
    assert rank_for(None, "Atlassian") == HEADLINE_RANK
    assert rank_for(None, "Deloitte") == MAJOR_RANK
    assert rank_for(None, "Some Unknown Startup") == UNRANKED_RANK
    assert rank_for(None, None) == UNRANKED_RANK


# A tier the bot does not recognise means the scraper added one without telling
# us. Sorting it last is wrong but harmless; raising would take out the recap.
def test_an_unrecognised_tier_sorts_last_rather_than_raising():
    assert rank_for("platinum", "Atlassian") == UNRANKED_RANK


# The drift check compares tier against tier, so the exported mapping has to
# report the same tier the ranking uses.
def test_local_tiers_matches_the_ranks():
    tiers = local_tiers()

    assert tiers[normalise_company("Atlassian")] == TIER_HEADLINE
    assert tiers[normalise_company("Deloitte")] == TIER_MAJOR
    assert normalise_company("Some Unknown Startup") not in tiers
    assert set(tiers.values()) == {TIER_HEADLINE, TIER_MAJOR}
