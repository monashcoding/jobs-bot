"""Thread names lead with the employer.

The forum list shows the start of a name and truncates the end, and the board is
scanned by company, so the company is what has to survive. The year went with
the reshuffle: every posting on the board is this or next year's intake, so it
said nothing and cost characters the role name needed.
"""

from src.core.functions.job_post import (
    CLOSED_PREFIX,
    MAX_THREAD_NAME,
    build_thread_name,
)


def test_basic_format():
    assert build_thread_name("ACME", "Software Engineer") == "ACME — Software Engineer"


def test_no_year_is_carried():
    name = build_thread_name("Google", "Graduate Dev")
    assert name == "Google — Graduate Dev"
    assert "[" not in name


# Callers slice to MAX_THREAD_NAME, and company-first means the truncation eats
# the end of the role rather than the name of the employer.
def test_long_name_not_truncated_here():
    name = build_thread_name("B" * 80, "A" * 80)
    assert len(name) > MAX_THREAD_NAME
    assert name[:MAX_THREAD_NAME].startswith("B" * 80)


def test_closed_prefix_sits_ahead_of_the_name():
    assert (
        CLOSED_PREFIX + build_thread_name("ACME", "Software Engineer")
        == "❌ ACME — Software Engineer"
    )
