"""The reconciliation commands work from JobPost records, which do not carry
board_eligible -- it lives on the Mongo document. So they have to ask Mongo, or
they reopen exactly the threads the board filter exists to keep out.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from src.core.functions.job_eligibility import fetch_board_eligible_ids


async def _insert(job_col, docs: list[dict]) -> None:
    await job_col._col().insert_many(docs)


async def test_only_eligible_ids_are_returned(job_col):
    await _insert(
        job_col,
        [
            {"_id": "a", "title": "Eligible", "board_eligible": True},
            {"_id": "b", "title": "Rejected", "board_eligible": False},
            # Never scored: default-deny, so it is not board material either.
            {"_id": "c", "title": "Unscored"},
        ],
    )

    with patch("src.core.functions.job_eligibility.job_col", job_col):
        ids = await fetch_board_eligible_ids()

    assert ids == {"a"}


async def test_ids_come_back_as_strings(job_col):
    # JobPost.job_id is a string; a set of ObjectIds would never match it and
    # would silently archive every thread.
    from bson import ObjectId

    oid = ObjectId()
    await _insert(job_col, [{"_id": oid, "title": "T", "board_eligible": True}])

    with patch("src.core.functions.job_eligibility.job_col", job_col):
        ids = await fetch_board_eligible_ids()

    assert ids == {str(oid)}
    assert all(isinstance(i, str) for i in ids)


async def test_empty_collection_is_empty_not_an_error(job_col):
    with patch("src.core.functions.job_eligibility.job_col", job_col):
        assert await fetch_board_eligible_ids() == set()


async def test_reset_open_state_reopens_only_active_eligible_jobs(job_col):
    """Drives the real command, so the query it actually issues is what is tested.

    Filtering on "not outdated" alone reopened every thread whose job the board
    filter excludes, which made this command undo the filter wholesale.
    """
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from src.backend.sql.models import JobPost
    from src.cogs.commands.jobs import JobsGroup

    await _insert(
        job_col,
        [
            {"_id": "keep", "title": "Active + eligible", "board_eligible": True},
            {
                "_id": "outdated",
                "title": "Eligible but outdated",
                "board_eligible": True,
                "outdated": True,
            },
            {
                "_id": "ineligible",
                "title": "Active but not board material",
                "board_eligible": False,
            },
            {"_id": "unscored", "title": "Active, never scored"},
        ],
    )

    def _post(job_id: str, thread_id: int) -> JobPost:
        return JobPost(
            job_id=job_id,
            guild_id=1,
            forum_post_id=thread_id,
            forum_channel_id=3,
            posted_at=datetime.now(tz=timezone.utc),
            title=job_id,
        )

    threads = {}

    async def fetch_channel(thread_id):
        thread = MagicMock()
        thread.id = thread_id
        thread.name = str(thread_id)
        thread.archived = False
        thread.edit = AsyncMock()
        threads[thread_id] = thread
        return thread

    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock(return_value=MagicMock(edit=AsyncMock()))
    interaction.client.fetch_channel = fetch_channel

    posts = [
        _post("keep", 1),
        _post("outdated", 2),
        _post("ineligible", 3),
        _post("unscored", 4),
    ]

    with (
        patch("src.cogs.commands.jobs.job_col", job_col),
        patch(
            "src.cogs.commands.jobs.job_post_db.get_all",
            new=AsyncMock(return_value=posts),
        ),
    ):
        await JobsGroup.reset_open_state.callback(JobsGroup(), interaction)

    def was_reopened(thread_id: int) -> bool:
        return any(
            call.kwargs.get("archived") is False
            for call in threads[thread_id].edit.await_args_list
        )

    assert was_reopened(1), "an active, board-eligible job should be reopened"
    assert not was_reopened(2), "an outdated job should stay closed"
    assert not was_reopened(3), "an ineligible job must not be put back on the board"
    assert not was_reopened(4), "an unscored job must not be put back on the board"


async def test_sync_query_excludes_closed_and_outdated_but_keeps_no_deadline(job_col):
    """The query sync_jobs issues, run against real MongoDB query semantics.

    The subtle one is `close_date: None`, which in MongoDB matches a missing
    field as well as an explicit null -- that is what a listing with no deadline
    looks like, and those must stay postable.
    """
    from datetime import datetime, timedelta, timezone

    from src.core.functions import job_post

    now = datetime.now(tz=timezone.utc)
    await _insert(
        job_col,
        [
            {
                "_id": "open",
                "title": "Open",
                "board_eligible": True,
                "close_date": now + timedelta(days=30),
            },
            {"_id": "no-deadline", "title": "Rolling", "board_eligible": True},
            {
                "_id": "null-deadline",
                "title": "Explicit null",
                "board_eligible": True,
                "close_date": None,
            },
            {
                "_id": "closed",
                "title": "Closed",
                "board_eligible": True,
                "close_date": now - timedelta(days=1),
            },
            {
                "_id": "outdated",
                "title": "Outdated",
                "board_eligible": True,
                "outdated": True,
                "close_date": now + timedelta(days=30),
            },
            {
                "_id": "ineligible",
                "title": "Not board material",
                "board_eligible": False,
                "close_date": now + timedelta(days=30),
            },
        ],
    )

    captured = {}

    async def capture(query, **kwargs):
        captured.update(query)
        return []

    with (
        patch.object(
            job_post.guild_config_db,
            "get_all",
            new=AsyncMock(return_value=[MagicMock(guild_id=1)]),
        ),
        patch.object(job_post.job_col, "find", new=capture),
    ):
        await job_post.sync_jobs(MagicMock())

    found = await job_col._col().find(captured, {"_id": 1}).to_list(None)

    assert {str(d["_id"]) for d in found} == {"open", "no-deadline", "null-deadline"}
