from src.core.functions.job_post import build_thread_name


def test_basic_format():
    assert build_thread_name("Software Engineer", "ACME", 2025) == "Software Engineer | ACME [2025]"


def test_different_year():
    assert build_thread_name("Graduate Dev", "Google", 2024) == "Graduate Dev | Google [2024]"


def test_long_name_not_truncated():
    # build_thread_name itself does not truncate; callers slice to 100
    name = build_thread_name("A" * 80, "B" * 80, 2025)
    assert "[2025]" in name
    assert len(name) > 100
