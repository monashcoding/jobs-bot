"""Rank a company by how recognisable it is, for ordering the weekly recap.

The scraper's notable-company list is a gate: a listing is either on the board
or it is not. That makes it useless for ordering, because every posting in the
recap has already passed it. Prominence needs a second axis, so the same names
are split into tiers here.

Tier 1 is the set of employers whose name alone makes someone open the message:
big tech, the quant trading firms, the top-tier banks and consultancies, and the
Australian companies with the same pull. Tier 2 is everything else on the board
-- still notable, still worth posting, just not what earns one of the eight
slots in a recap when a headline name is competing for it.

Keeping this in step with the scraper's list is manual, because the two lists
live in different repositories. The scraper is the authority on *whether* a
company belongs on the board and this file is only about *ordering* what is
already there, so drift degrades the recap's ordering rather than letting an
unwanted employer through: a company the scraper adds and this file has not
tiered still gets posted, it just never wins one of the recap's few slots.

scripts/check_company_drift.py names the difference in both directions. Point it
at the scraper's companies.go after changing either list:

    scripts/check_company_drift.py ../jobs-scraper/utils/companies.go

Setting JOBS_SCRAPER_COMPANIES to that path also turns on the drift test in
tests/test_company_drift.py, which is skipped without it.
"""

from __future__ import annotations

import re
from typing import Final

# Ranks are compared directly, so lower sorts earlier.
HEADLINE_RANK: Final[int] = 0
MAJOR_RANK: Final[int] = 1
UNRANKED_RANK: Final[int] = 2

# The tier vocabulary the scraper writes to ``company_tier`` on each Mongo
# document. These strings are a contract with the scraper, not an internal
# detail: changing one here without changing it there silently sends every
# posting to the bottom of the recap.
TIER_HEADLINE: Final[str] = "headline"
TIER_MAJOR: Final[str] = "major"
TIER_UNRANKED: Final[str] = "unranked"

_TIER_ORDER: Final[dict[str, int]] = {
    TIER_HEADLINE: HEADLINE_RANK,
    TIER_MAJOR: MAJOR_RANK,
    TIER_UNRANKED: UNRANKED_RANK,
}

# --- Tier 1: the names that carry the message -------------------------------
_HEADLINE_NAMES: Final[list[str]] = [
    # Big tech and global product companies
    "Google",
    "Alphabet",
    "Microsoft",
    "Amazon",
    "Amazon Web Services",
    "AWS",
    "Apple",
    "Meta",
    "TikTok",
    "ByteDance",
    "Netflix",
    "NVIDIA",
    "OpenAI",
    "Anthropic",
    "Stripe",
    "Figma",
    "Databricks",
    "Palantir",
    "Snowflake",
    "Canva",
    "Atlassian",
    "Airbnb",
    "Uber",
    "Spotify",
    "LinkedIn",
    "GitHub",
    "Tesla",
    "Bloomberg",
    "Adobe",
    "Salesforce",
    "Oracle",
    "IBM",
    "Intel",
    "AMD",
    "Qualcomm",
    "Cisco",
    "SAP",
    "Block",
    "Square",
    "PayPal",
    "Shopify",
    "Datadog",
    "MongoDB",
    "Cloudflare",
    "Sony",
    "Samsung",
    "Tencent",
    # Quantitative trading and market making. Small firms by headcount, but the
    # single strongest draw for this audience, so the whole block sits in tier 1.
    "Optiver",
    "Jane Street",
    "IMC Trading",
    "IMC",
    "Susquehanna International Group",
    "Susquehanna",
    "SIG",
    "Citadel",
    "Citadel Securities",
    "Jump Trading",
    "Akuna Capital",
    "Tower Research Capital",
    "Virtu Financial",
    "Two Sigma",
    "DRW",
    "Hudson River Trading",
    "Vivienne Court Trading",
    "VivCourt",
    "Eclipse Trading",
    "Millennium",
    "Point72",
    "Squarepoint Capital",
    "Maven Securities",
    "XTX Markets",
    "Qube Research and Technologies",
    "QRT",
    "Flow Traders",
    "Old Mission Capital",
    "Five Rings",
    "Radix Trading",
    "WorldQuant",
    "AQR Capital Management",
    "Man Group",
    "Balyasny",
    "Schonfeld",
    "Vatic Labs",
    "Headlands Technologies",
    "Wolverine Trading",
    "Belvedere Trading",
    "PEAK6",
    # Investment banks and strategy consulting with competitive grad programs.
    "Goldman Sachs",
    "J.P. Morgan",
    "JPMorgan Chase",
    "Morgan Stanley",
    "Macquarie Group",
    "Macquarie",
    "UBS",
    "Citi",
    "Citigroup",
    "Bank of America",
    "McKinsey & Company",
    "Boston Consulting Group",
    "Bain & Company",
    # Australian technology with national name recognition.
    "Airwallex",
    "WiseTech Global",
    "Xero",
    "SEEK",
    "REA Group",
    "Immutable",
    "SafetyCulture",
    "Culture Amp",
    "Linktree",
    "Quantium",
    "Atlassian",
    # Australian household names outside tech.
    "Commonwealth Bank",
    "CommBank",
    "Telstra",
    "Qantas",
    "Woolworths Group",
    "Woolworths",
    "Coles Group",
    "Coles",
    "BHP",
    "Rio Tinto",
    "CSIRO",
    "Australian Signals Directorate",
    "CSL",
    "Cochlear",
    "ResMed",
]

# --- Tier 2: the rest of the board ------------------------------------------
_MAJOR_NAMES: Final[list[str]] = [
    # Remaining global technology
    "Arm",
    "Netflix",
    "Twilio",
    "Zoom",
    "Dropbox",
    "GitLab",
    "Canonical",
    "Red Hat",
    "VMware",
    "ServiceNow",
    "Workday",
    "Elastic",
    "Confluent",
    "HashiCorp",
    "Akamai",
    "eBay",
    "Expedia",
    "Booking.com",
    "Mastercard",
    "Visa",
    "Siemens",
    "Ericsson",
    "Dell",
    "Dell Technologies",
    "Hewlett Packard Enterprise",
    "Motorola Solutions",
    "Lenovo",
    # Banks, insurers, exchanges and financial services
    "Westpac",
    "NAB",
    "National Australia Bank",
    "ANZ",
    "Suncorp Group",
    "Suncorp",
    "IAG",
    "Insurance Australia Group",
    "AMP",
    "QBE",
    "Allianz",
    "Bendigo Bank",
    "Bendigo and Adelaide Bank",
    "Reserve Bank of Australia",
    "ASX",
    "Australian Securities Exchange",
    "HSBC",
    "Deutsche Bank",
    "BNP Paribas",
    "Nomura",
    "Jarden",
    "Barrenjoey",
    "Challenger",
    "Rabobank",
    "Colonial First State",
    "Afterpay",
    "Zip",
    "Tyro",
    "Judo Bank",
    # Consulting and professional services
    "Accenture",
    "Deloitte",
    "PwC",
    "KPMG",
    "Ernst & Young",
    "EY",
    "Capgemini",
    "Infosys",
    "Tata Consultancy Services",
    "Wipro",
    "Cognizant",
    "Thoughtworks",
    "Mantel Group",
    "Kearney",
    "Oliver Wyman",
    "L.E.K. Consulting",
    "Nous Group",
    "Slalom",
    "Grant Thornton",
    "BDO",
    "RSM",
    "FTI Consulting",
    "Alvarez & Marsal",
    "KordaMentha",
    "Scyne Advisory",
    "Avanade",
    "DXC Technology",
    "NTT Data",
    "Fujitsu",
    "Protiviti",
    # Remaining Australian technology
    "CAR Group",
    "Carsales",
    "Domain Group",
    "TechnologyOne",
    "Altium",
    "Megaport",
    "NEXTDC",
    "Nearmap",
    "Employment Hero",
    "Go1",
    "Deputy",
    "Envato",
    "Octopus Deploy",
    "Redbubble",
    "Rokt",
    "Airtasker",
    "Kogan",
    "Prospa",
    "Zeller",
    "Eucalyptus",
    "UpGuard",
    "DroneShield",
    "Gilmour Space Technologies",
    "Computershare",
    "IRESS",
    "Aristocrat",
    "Telix Pharmaceuticals",
    # Telco, retail and other major Australian employers
    "Optus",
    "TPG Telecom",
    "Vocus",
    "NBN Co",
    "Australia Post",
    "Wesfarmers",
    "Bunnings",
    "Virgin Australia",
    "Transurban",
    # Defence, government and research
    "Australian Security Intelligence Organisation",
    "Department of Defence",
    "Defence Science and Technology Group",
    "Data61",
    "BAE Systems",
    "Leidos",
    "Lockheed Martin",
    "Boeing",
    "Thales",
    "Northrop Grumman",
    "Raytheon",
    "Australian Taxation Office",
    "Department of Home Affairs",
    "Services Australia",
    "Australian Bureau of Statistics",
    "Australian Federal Police",
    "Australian Energy Market Operator",
    "AEMO",
    "Digital Transformation Agency",
    "Australian Securities and Investments Commission",
    # Cyber security
    "CrowdStrike",
    "Palo Alto Networks",
    "CyberCX",
    "Splunk",
    "Okta",
    "Fortinet",
    "SentinelOne",
    "Tenable",
    "Rapid7",
    "Wiz",
    "Zscaler",
    "Check Point Software Technologies",
    "Sophos",
    # Energy and resources
    "Fortescue",
    "Woodside Energy",
    "Woodside",
    "Santos",
    "Origin Energy",
    "AGL Energy",
    "AGL",
]

# --- Order inside tier 1 ----------------------------------------------------
# Tier 1 is still too coarse for a ten-line list: Canva and a tier 1 bank tie,
# and the tie breaks on whichever happened to be posted first that week. These
# are the names with the most pull for this audience -- Australian students --
# ordered, so a quiet week leads with the ones people open the message for.
#
# A judgement call, and meant to be reshuffled: nothing downstream depends on
# the order beyond which of two equally quiet threads is listed first, and a
# name missing from here still sorts ahead of every tier 2 company.
_TOP_NAMES: Final[list[str]] = [
    "Canva",
    "Atlassian",
    "Google",
    "Optiver",
    "Jane Street",
    "Citadel Securities",
    "Jump Trading",
    "IMC Trading",
    "Susquehanna",
    "Microsoft",
    "Amazon",
    "Apple",
    "Meta",
    "NVIDIA",
    "OpenAI",
    "Anthropic",
    "Stripe",
    "Figma",
    "Macquarie",
    "Goldman Sachs",
    "J.P. Morgan",
    "McKinsey & Company",
    "Boston Consulting Group",
    "Commonwealth Bank",
    "Airwallex",
]

# Country and legal-entity suffixes, stripped so the many spellings of one
# employer collapse together: "Thales Australia", "Google Australia Pty Ltd" and
# "Amazon AU" all have to reach the same key as the bare name.
_SUFFIX_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\s*(?:"
    r"pty\.?|ltd\.?|limited|inc\.?|incorporated|llc|llp|plc|corp\.?|corporation|"
    r"co\.?|group|holdings|australia|australian|au|anz|apac|nz|new zealand|"
    r"asia pacific|global|international|technologies|technology|"
    # Connectors left dangling once the suffix behind them goes, as in
    # "Commonwealth Bank of Australia".
    r"of|the|and|&"
    r")\b\.?\s*$",
    re.IGNORECASE,
)

# Everything that is not alphanumeric, so casing, punctuation and spacing
# differences between sources collapse to one key.
_NOISE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def normalise_company(name: str) -> str:
    """Reduce a company name to a comparable key.

    Mirrors the scraper's normalisation: drop a trailing parenthetical (usually
    an abbreviation of what precedes it), strip country and legal-entity
    suffixes, then remove all remaining punctuation and casing.
    """
    text = name.strip()

    if (open_paren := text.find("(")) != -1:
        text = text[:open_paren]

    # Repeated, because "Google Australia Pty Ltd" carries three of them.
    previous = None
    while previous != text:
        previous = text
        text = _SUFFIX_PATTERN.sub("", text).strip()

    return _NOISE_PATTERN.sub("", text.lower())


def _build(names: list[str], rank: int, into: dict[str, int]) -> None:
    for name in names:
        if key := normalise_company(name):
            # First tier to claim a name keeps it, so a company listed in both
            # blocks ranks by the better of the two.
            into.setdefault(key, rank)


_RANKS: Final[dict[str, int]] = {}
_build(_HEADLINE_NAMES, HEADLINE_RANK, _RANKS)
_build(_MAJOR_NAMES, MAJOR_RANK, _RANKS)


_RANK_TO_TIER: Final[dict[int, str]] = {
    HEADLINE_RANK: TIER_HEADLINE,
    MAJOR_RANK: TIER_MAJOR,
    UNRANKED_RANK: TIER_UNRANKED,
}


def local_tiers() -> dict[str, str]:
    """Return this file's normalised company key to tier mapping.

    Exposed for the drift check, which compares it against the scraper's own
    tier slices; nothing in the bot needs it at runtime. Goes when the fallback
    goes.
    """
    return {key: _RANK_TO_TIER[rank] for key, rank in _RANKS.items()}


def company_rank(name: str | None) -> int:
    """Return a company's prominence rank; lower is more prominent.

    An unknown or missing employer sorts last rather than being dropped: the
    scraper already decided it belongs on the board, and this file only decides
    what gets shown first.
    """
    if not name:
        return UNRANKED_RANK
    return _RANKS.get(normalise_company(name), UNRANKED_RANK)


def rank_for(company_tier: str | None, company_name: str | None) -> int:
    """Return a posting's prominence rank, preferring the scraper's tier.

    The tier is authoritative wherever it exists, because the scraper owns the
    company list; the local tables above are a fallback for documents written
    before it started emitting one, and for anything it declines to classify.

    A missing tier falls back rather than failing, and an unrecognised tier
    sorts last rather than raising. This is deliberately unlike
    ``is_board_eligible``, which is default-deny: a missing ``board_eligible``
    means a job was never scored and posting it risks posting the whole
    collection, so it is refused. A missing ``company_tier`` only means the bot
    does not know where to rank a job it has already decided to post, and the
    worst case is a good listing shown a few lines further down. Failing closed
    there would drop real postings out of the recap to fix a cosmetic problem.

    Delete the fallback -- and everything above it -- once no document the recap
    can reach is missing a tier. ``/jobs diagnostics`` reports that count.
    """
    if company_tier is not None:
        return _TIER_ORDER.get(company_tier, UNRANKED_RANK)
    return company_rank(company_name)


# Sorts after every listed name, so an unlisted company keeps its tier and only
# loses the order within it.
UNLISTED_TOP_RANK: Final[int] = len(_TOP_NAMES)

_TOP_RANKS: Final[dict[str, int]] = {}
for _position, _name in enumerate(_TOP_NAMES):
    if _key := normalise_company(_name):
        # First spelling wins, as in the tier tables above.
        _TOP_RANKS.setdefault(_key, _position)


def top_rank(name: str | None) -> int:
    """Return a company's position within the top names; lower sorts earlier."""
    if not name:
        return UNLISTED_TOP_RANK
    return _TOP_RANKS.get(normalise_company(name), UNLISTED_TOP_RANK)


def recap_rank(company_tier: str | None, company_name: str | None) -> tuple[int, int]:
    """Return a posting's prominence as (tier, position within the tier).

    The recap's tiebreak, once engagement has had its say. Kept separate from
    ``rank_for`` because the tier is the contract with the scraper while the
    order inside it is this file's own opinion, and everything outside the
    recap wants only the tier.
    """
    return rank_for(company_tier, company_name), top_rank(company_name)
