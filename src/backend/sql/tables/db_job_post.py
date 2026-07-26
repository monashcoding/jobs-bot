from __future__ import annotations

from typing import Final

from sqlmodel import select

from src.backend.sql.models import DeadlineReminder, JobPost
from src.backend.sql.tables.base import BaseDB


class JobPostDB(BaseDB[JobPost]):
    model = JobPost

    async def get_by_job_id(self, job_id: str) -> list[JobPost]:
        """Return all job posts for a given job (one per guild)."""
        async with self._session() as s:
            result = await s.exec(select(JobPost).where(JobPost.job_id == job_id))
            return list(result.all())

    async def get_by_forum_post_id(self, forum_post_id: int) -> list[JobPost]:
        """Return all job posts matching a Discord thread ID."""
        async with self._session() as s:
            result = await s.exec(
                select(JobPost).where(JobPost.forum_post_id == forum_post_id)
            )
            return list(result.all())

    async def get_pending_deletions(self) -> list[JobPost]:
        """Return all job posts currently awaiting deletion confirmation."""
        async with self._session() as s:
            result = await s.exec(
                select(JobPost).where(JobPost.awaiting_deletion == True)
            )
            return list(result.all())

    async def set_awaiting_deletion(
        self,
        job_id: str,
        guild_id: int,
        *,
        deletion_message_id: int,
    ) -> JobPost | None:
        """Mark a job post as awaiting deletion and record the prompt message ID."""
        async with self._session() as s:
            obj = await s.get(JobPost, (job_id, guild_id))
            if obj is None:
                return None
            obj.awaiting_deletion = True
            obj.deletion_message_id = deletion_message_id
            s.add(obj)
            await s.commit()
            await s.refresh(obj)
            return obj

    async def clear_awaiting_deletion(
        self, job_id: str, guild_id: int
    ) -> JobPost | None:
        """Clear the awaiting_deletion flag (used when keeping a post)."""
        async with self._session() as s:
            obj = await s.get(JobPost, (job_id, guild_id))
            if obj is None:
                return None
            obj.awaiting_deletion = False
            obj.deletion_message_id = None
            s.add(obj)
            await s.commit()
            await s.refresh(obj)
            return obj

    async def get_active_with_close_date(self) -> list[JobPost]:
        """Return posts that have a close_date and have not yet been marked closed."""
        async with self._session() as s:
            result = await s.exec(
                select(JobPost).where(
                    JobPost.close_date.isnot(None),
                    JobPost.awaiting_deletion == False,
                )
            )
            posts = list(result.all())
        return [
            p for p in posts if DeadlineReminder.CLOSED not in p.deadline_reminders_sent
        ]

    async def mark_reminder_sent(
        self, job_id: str, guild_id: int, reminder: DeadlineReminder
    ) -> None:
        """Append a reminder stage to deadline_reminders_sent if not already present."""
        async with self._session() as s:
            obj = await s.get(JobPost, (job_id, guild_id))
            if obj is None:
                return
            if reminder not in obj.deadline_reminders_sent:
                obj.deadline_reminders_sent = [
                    *obj.deadline_reminders_sent,
                    reminder.value,
                ]
            s.add(obj)
            await s.commit()


job_post_db: Final[JobPostDB] = JobPostDB()
