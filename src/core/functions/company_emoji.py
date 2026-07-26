"""Match a company name to its Discord emoji.

The current implementation uses keyword pattern matching as a demo.
A future version will replace / supplement this with a DB-backed lookup
once the company→emoji mapping table is available.
"""

from __future__ import annotations

import re
from typing import Final

from discord import PartialEmoji

from src.core import emojis

# ---------------------------------------------------------------------------
# Pattern table
# Checked in order; first match wins.
# Put longer / more-specific phrases before shorter ones to avoid
# early false matches (e.g. "commonwealth bank" before "bank").
# ---------------------------------------------------------------------------
_PATTERNS: Final[list[tuple[str, PartialEmoji]]] = [
    # --- High-frequency tech ---
    ("google", emojis.GOOGLE),
    ("tiktok", emojis.TIKTOK),
    ("canva", emojis.CANVA),
    ("atlassian", emojis.ATLASSIAN),
    ("mongodb", emojis.MONGODB),
    ("apple", emojis.APPLE),
    ("stripe", emojis.STRIPE),
    ("palantir", emojis.PALANTIR),
    ("arista", emojis.ARISTA),
    ("microsoft", emojis.MICROSOFT),
    ("amazon", emojis.AMAZON),
    ("square", emojis.SQUARE),
    ("block inc", emojis.SQUARE),  # Square rebranded
    ("snapchat", emojis.SNAP),
    ("snap", emojis.SNAP),
    ("the trade desk", emojis.THE_TRADE_DESK),
    ("spotify", emojis.SPOTIFY),
    ("rokt", emojis.ROKT),
    ("airwallex", emojis.AIRWALLEX),
    # --- AU tech / fintech ---
    ("xero", emojis.XERO),
    ("tyro", emojis.TYRO),
    ("culture amp", emojis.CULTURE_AMP),
    ("macquarie", emojis.MACQUARIE_GROUP),
    ("commonwealth bank", emojis.COMMBANK),
    ("commbank", emojis.COMMBANK),
    ("mastercard", emojis.MASTERCARD),
    ("goldman sachs", emojis.GOLDMAN_SACHS),
    ("bank of america", emojis.BANK_OF_AMERICA),
    ("luxury escapes", emojis.LUXURY_ESCAPES),
    ("dovetail", emojis.DOVETAIL),
    ("expedia", emojis.EXPEDIA),
    ("appian", emojis.APPIAN),
    ("relevance ai", emojis.RELEVANCE_AI),
    ("advanced micro devices", emojis.AMD),
    ("adobe", emojis.ADOBE),
    ("droneshield", emojis.DRONESHIELD),
    ("oracle", emojis.ORACLE),
    ("salesforce", emojis.SALESFORCE),
    ("dolby", emojis.DOLBY),
    # --- AU companies ---
    ("cisco", emojis.CISCO),
    ("sportsbet", emojis.SPORTSBET),
    ("quantium", emojis.QUANTIUM),
    ("gitlab", emojis.GITLAB),
    ("coles", emojis.COLES),
    ("woolworths", emojis.WOOLWORTHS),
    ("eucalyptus", emojis.EUCALYPTUS),
    ("honeywell", emojis.HONEYWELL),
    ("zendesk", emojis.ZENDESK),
    ("leidos", emojis.LEIDOS),
    (
        "car group",
        emojis.CARSALES,
    ),  # CAR Group Ltd (ASX:CAR) is the listed parent of carsales.com.au
    ("carsales", emojis.CARSALES),
    ("seek", emojis.SEEK),
    ("realestate.com", emojis.REA),
    ("rea group", emojis.REA),
    ("easygo", emojis.EASYGO),
    ("linktree", emojis.LINKTREE),
    ("australiansuper", emojis.AUSSUPER),
    ("australian super", emojis.AUSSUPER),
    ("reecetech", emojis.REECETECH),
    ("reece group", emojis.REECETECH),
    ("freelancer", emojis.FREELANCER),
    ("optus", emojis.OPTUS),
    ("slalom", emojis.SLALOM),
    ("myob", emojis.MYOB),
    ("leap dev", emojis.LEAP_DEV),
    ("channel nine", emojis.NINE),
    ("nine", emojis.NINE),  # "Nine" is the current brand name
    ("national australia bank", emojis.NAB),
    ("australia and new zealand banking", emojis.ANZ),
    ("domain group", emojis.DOMAIN),
    ("domain.com", emojis.DOMAIN),
    ("australian defence force", emojis.ADF),
    ("medibank", emojis.MEDIBANK),
    ("resmed", emojis.RESMED),
    ("cochlear", emojis.COCHLEAR),
    ("westpac", emojis.WESTPAC),
    ("service nsw", emojis.SERVICE_NSW),
    ("telstra", emojis.TELSTRA),
    # --- Consulting / professional services ---
    ("ernst & young", emojis.EY),
    ("ernst and young", emojis.EY),
    (
        "ernst young",
        emojis.EY,
    ),  # & normalises to a space, so "Ernst & Young" → "ernst young"
    ("deloitte", emojis.DELOITTE),
    ("pricewaterhousecoopers", emojis.PWC),
    ("kpmg", emojis.KPMG),
    ("accenture", emojis.ACCENTURE),
    ("thoughtworks", emojis.THOUGHTWORKS),
    ("dxc technology", emojis.DXC),
    ("wipro", emojis.WIPRO),
    ("infosys", emojis.INFOSYS),
    ("tata consultancy", emojis.TCS),
    ("cognizant", emojis.COGNIZANT),
    ("fdm group", emojis.FDM_GROUP),
    ("lyra", emojis.LYRA),
    # --- Trading / quant finance ---
    ("jane street", emojis.JANE_STREET),
    ("hudson river trading", emojis.HUDSON_RIVER_TRADING),
    ("two sigma", emojis.TWO_SIGMA),
    ("jump trading", emojis.JUMP_TRADING),
    ("vivcourt", emojis.VIVCOURT_TRADING),
    ("akuna capital", emojis.AKUNA_CAPITAL),
    ("susquehanna", emojis.SIG),
    ("citadel", emojis.CITADEL),
    ("optiver", emojis.OPTIVER),
    ("qube research", emojis.QRT),
    # --- Short acronyms (whole-word matched, placed last to avoid false hits) ---
    ("amd", emojis.AMD),
    ("vgw", emojis.VGW),
    ("rea", emojis.REA),
    ("nab", emojis.NAB),
    ("anz", emojis.ANZ),
    ("adf", emojis.ADF),
    ("nri", emojis.NRI),
    ("dxc", emojis.DXC),
    ("hcltech", emojis.HCL),  # "HCLTech" is the current brand name
    ("hcl", emojis.HCL),
    ("tcs", emojis.TCS),
    ("fdm", emojis.FDM_GROUP),
    ("hrt", emojis.HUDSON_RIVER_TRADING),
    ("imc", emojis.IMC),
    ("qrt", emojis.QRT),
    ("pwc", emojis.PWC),
    ("ey", emojis.EY),
]

# Keywords this length or shorter use whole-word regex matching.
_SHORT_THRESHOLD: Final[int] = 6


def _matches(keyword: str, normalized: str) -> bool:
    if len(keyword) <= _SHORT_THRESHOLD:
        return bool(re.search(rf"\b{re.escape(keyword)}\b", normalized))
    return keyword in normalized


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def get_company_emoji(company_name: str) -> PartialEmoji | None:
    """Return the emoji for *company_name*, or None if no match is found.

    Matching is case-insensitive substring search (whole-word for short
    acronyms). The first pattern that matches wins, so the table is ordered
    from most-specific to least-specific.

    TODO: replace / augment with a DB-backed lookup once the mapping table
    is available.
    """
    normalized = _normalize(company_name)
    for keyword, emoji in _PATTERNS:
        if _matches(keyword, normalized):
            return emoji
    return None
