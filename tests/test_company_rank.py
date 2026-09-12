"""Company prominence ranking, which decides what a recap shows first.

The scraper's notable-company list decides what reaches the board at all. It is
a flat gate, so it cannot order what it lets through -- these tiers do.
"""

from src.core.functions.company_rank import (
    _TOP_NAMES,
    HEADLINE_RANK,
    MAJOR_RANK,
    TIER_HEADLINE,
    TIER_MAJOR,
    TIER_UNRANKED,
    UNLISTED_TOP_RANK,
    UNRANKED_RANK,
    company_rank,
    local_tiers,
    normalise_company,
    rank_for,
    recap_rank,
    top_rank,
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


# The headline tier is too coarse for a ten-line recap on its own: Canva and a
# tier 1 bank tie, and the tie breaks on whichever was posted first.
def test_top_names_order_within_the_headline_tier():
    assert top_rank("Canva") < top_rank("Google")
    assert top_rank("Google") < top_rank("Macquarie")
    # Spellings collapse the same way the tiers do.
    assert top_rank("Google Australia Pty Ltd") == top_rank("Google")


def test_an_unlisted_company_sorts_after_every_named_draw():
    assert top_rank("Cochlear") == UNLISTED_TOP_RANK
    assert top_rank("Some Unknown Startup") == UNLISTED_TOP_RANK
    assert top_rank(None) == UNLISTED_TOP_RANK
    assert top_rank("Canva") < UNLISTED_TOP_RANK


# The tier is still the first thing compared: losing the order within a tier is
# cosmetic, but a tier 2 company ahead of a tier 1 one is the recap's whole job
# done wrong.
def test_tier_beats_position_within_it():
    assert recap_rank(TIER_HEADLINE, "Cochlear") < recap_rank(TIER_MAJOR, "Canva")
    assert recap_rank(TIER_HEADLINE, "Canva") < recap_rank(TIER_HEADLINE, "Cochlear")
    assert recap_rank(None, "Atlassian") < recap_rank(None, "Deloitte")


# The order is an opinion about which names carry a message, so every one of
# them has to be a name the bot already considers headline -- otherwise it is
# ordering a tier the company is not in.
def test_every_top_name_is_in_the_headline_tier():
    tiers = local_tiers()
    for name in _TOP_NAMES:
        assert tiers[normalise_company(name)] == TIER_HEADLINE, name
