from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import or_
from sqlmodel import select

from src.backend.sql.models import DeadlineReminder, JobPost
from src.backend.sql.tables.base import BaseDB


class JobPostDB(BaseDB[JobPost]):
    model = JobPost

    async def get_all(self) -> list[JobPost]:
        """Return all job posts."""
        async with self._session() as s:
            result = await s.exec(select(JobPost))
            return list(result.all())

    async def get_by_guild(self, guild_id: int) -> list[JobPost]:
        """Return every job post belonging to one guild."""
        async with self._session() as s:
            result = await s.exec(select(JobPost).where(JobPost.guild_id == guild_id))
            return list(result.all())

    async def delete_by_guild(self, guild_id: int) -> int:
        """Delete every job post record for one guild. Returns the count deleted.

        Scoped to a guild so a rebuild in one server cannot orphan another
        server's threads: the records are what tell the bot a thread already
        exists, and a thread whose record is gone is invisible to it forever.
        """
        async with self._session() as s:
            result = await s.exec(select(JobPost).where(JobPost.guild_id == guild_id))
            posts = list(result.all())
            for post in posts:
                await s.delete(post)
            await s.commit()
            return len(posts)

    async def restore_posted_at(
        self, guild_id: int, posted_at_by_job: dict[str, datetime]
    ) -> int:
        """Reinstate original posted_at values after a rebuild. Returns the count set.

        A rebuilt thread is a new thread, so it is stamped with the time it was
        created. That would make the whole board look new to anything reading
        posted_at -- the weekly recap most of all, which would then announce the
        entire board as this week's postings and ping every role about it. The
        posting date belongs to the job, not to the thread that happens to be
        showing it, so it is carried across.

        Jobs with no previous post keep their new timestamp: they really are new.
        """
        if not posted_at_by_job:
            return 0
        async with self._session() as s:
            result = await s.exec(
                select(JobPost)
                .where(JobPost.guild_id == guild_id)
                .where(JobPost.job_id.in_(posted_at_by_job.keys()))
            )
            posts = list(result.all())
            for post in posts:
                post.posted_at = posted_at_by_job[post.job_id]
                s.add(post)
            await s.commit()
            return len(posts)

    async def get_by_job_id(self, job_id: str) -> list[JobPost]:
        """Return all job posts for a given job (one per guild)."""
        async with self._session() as s:
            result = await s.exec(select(JobPost).where(JobPost.job_id == job_id))
            return list(result.all())

    async def sync_fields(self, job_id: str, guild_id: int, **fields) -> None:
        """Update denormalized fields on a JobPost from a MongoDB document."""
        async with self._session() as s:
            obj = await s.get(JobPost, (job_id, guild_id))
            if obj is None:
                return
            for key, value in fields.items():
                setattr(obj, key, value)
            s.add(obj)
            await s.commit()

    async def get_by_forum_post_id(self, forum_post_id: int) -> list[JobPost]:
        """Return all job posts matching a Discord thread ID."""
        async with self._session() as s:
            result = await s.exec(
                select(JobPost).where(JobPost.forum_post_id == forum_post_id)
            )
            return list(result.all())

    async def get_posted_since(self, guild_id: int, since: datetime) -> list[JobPost]:
        """Return this guild's posts created on or after *since*, oldest first.

        Backs the weekly recap: posted_at is when the thread was created, which
        is what "new this week" means to a reader, rather than when the listing
        first appeared at the source.
        """
        async with self._session() as s:
            result = await s.exec(
                select(JobPost)
                .where(JobPost.guild_id == guild_id)
                .where(JobPost.posted_at >= since)
                .order_by(JobPost.posted_at)
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
        """Return posts that have a close_date or are outdated and have not yet been marked closed."""
        async with self._session() as s:
            result = await s.exec(
                select(JobPost).where(
                    or_(
                        JobPost.close_date.isnot(None),
                        JobPost.outdated == True,
                    ),
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
