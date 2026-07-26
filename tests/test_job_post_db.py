from datetime import datetime, timezone

import pytest

from src.backend.sql.models import DeadlineReminder, JobPost
from src.backend.sql.tables import JobPostDB


def _make_post(job_id: str, guild_id: int = 1, **kwargs) -> JobPost:
    defaults = {
        "forum_post_id": 999,
        "forum_channel_id": 888,
        "posted_at": datetime.now(tz=timezone.utc),
        "title": "Test Job",
        "company_name": "ACME",
    }
    defaults.update(kwargs)
    return JobPost(job_id=job_id, guild_id=guild_id, **defaults)


async def test_get_active_with_close_date_returns_open(job_post_db: JobPostDB):
    post = _make_post("aaa", close_date=datetime(2099, 1, 1, tzinfo=timezone.utc))
    await job_post_db.upsert(post)
    active = await job_post_db.get_active_with_close_date()
    assert any(p.job_id == "aaa" for p in active)


async def test_get_active_excludes_no_close_date(job_post_db: JobPostDB):
    await job_post_db.upsert(_make_post("bbb"))
    active = await job_post_db.get_active_with_close_date()
    assert not any(p.job_id == "bbb" for p in active)


async def test_get_active_excludes_closed(job_post_db: JobPostDB):
    post = _make_post(
        "ccc",
        close_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
        deadline_reminders_sent=[DeadlineReminder.CLOSED.value],
    )
    await job_post_db.upsert(post)
    active = await job_post_db.get_active_with_close_date()
    assert not any(p.job_id == "ccc" for p in active)


async def test_get_active_excludes_awaiting_deletion(job_post_db: JobPostDB):
    post = _make_post(
        "ddd",
        close_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
        awaiting_deletion=True,
    )
    await job_post_db.upsert(post)
    active = await job_post_db.get_active_with_close_date()
    assert not any(p.job_id == "ddd" for p in active)


async def test_mark_reminder_sent_appends(job_post_db: JobPostDB):
    await job_post_db.upsert(_make_post("eee"))
    await job_post_db.mark_reminder_sent("eee", 1, DeadlineReminder.REMINDER_1W)
    post = await job_post_db.get("eee", 1)
    assert DeadlineReminder.REMINDER_1W.value in post.deadline_reminders_sent


async def test_mark_reminder_sent_idempotent(job_post_db: JobPostDB):
    await job_post_db.upsert(_make_post("fff"))
    await job_post_db.mark_reminder_sent("fff", 1, DeadlineReminder.REMINDER_1D)
    await job_post_db.mark_reminder_sent("fff", 1, DeadlineReminder.REMINDER_1D)
    post = await job_post_db.get("fff", 1)
    assert post.deadline_reminders_sent.count(DeadlineReminder.REMINDER_1D.value) == 1


async def test_mark_reminder_sent_missing_is_noop(job_post_db: JobPostDB):
    # Should not raise for a non-existent record
    await job_post_db.mark_reminder_sent("nonexistent", 1, DeadlineReminder.REMINDER_2W)


async def test_get_by_job_id(job_post_db: JobPostDB):
    await job_post_db.upsert(_make_post("ggg", guild_id=1))
    await job_post_db.upsert(_make_post("ggg", guild_id=2))
    posts = await job_post_db.get_by_job_id("ggg")
    assert len(posts) == 2
    assert all(p.job_id == "ggg" for p in posts)


async def test_set_and_clear_awaiting_deletion(job_post_db: JobPostDB):
    await job_post_db.upsert(_make_post("hhh"))
    updated = await job_post_db.set_awaiting_deletion("hhh", 1, deletion_message_id=777)
    assert updated is not None
    assert updated.awaiting_deletion is True
    assert updated.deletion_message_id == 777

    cleared = await job_post_db.clear_awaiting_deletion("hhh", 1)
    assert cleared is not None
    assert cleared.awaiting_deletion is False
    assert cleared.deletion_message_id is None


async def test_get_pending_deletions(job_post_db: JobPostDB):
    await job_post_db.upsert(
        _make_post("iii", awaiting_deletion=True, deletion_message_id=1)
    )
    await job_post_db.upsert(_make_post("jjj"))
    pending = await job_post_db.get_pending_deletions()
    ids = {p.job_id for p in pending}
    assert "iii" in ids
    assert "jjj" not in ids


@pytest.mark.parametrize(
    "reminder",
    [
        DeadlineReminder.REMINDER_2W,
        DeadlineReminder.REMINDER_1W,
        DeadlineReminder.REMINDER_3D,
        DeadlineReminder.REMINDER_1D,
        DeadlineReminder.CLOSED,
    ],
)
async def test_all_reminder_values_can_be_stored(
    job_post_db: JobPostDB, reminder: DeadlineReminder
):
    job_id = f"rem_{reminder.value}"
    await job_post_db.upsert(_make_post(job_id))
    await job_post_db.mark_reminder_sent(job_id, 1, reminder)
    post = await job_post_db.get(job_id, 1)
    assert reminder.value in post.deadline_reminders_sent
