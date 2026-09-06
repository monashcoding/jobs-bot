"""/sync died in a channel the bot cannot read.

Discord dispatches a slash command whatever the bot's access to the channel it
was run in, but reading a message back from that channel needs View Channel and
Read Message History. /sync fetched its own progress message that way and raised
403 before a single job was posted -- losing the entire sync over a counter.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from src.cogs.commands.jobs import JobsGroup
from src.core.functions.job_post import SyncResult


def _forbidden() -> discord.Forbidden:
    response = MagicMock(status=403, reason="Forbidden")
    return discord.Forbidden(response, {"code": 50001, "message": "Missing Access"})


def _interaction(fetch_message=None) -> MagicMock:
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock(
        return_value=MagicMock(id=7, edit=AsyncMock())
    )
    interaction.channel.fetch_message = fetch_message or AsyncMock(
        return_value=MagicMock(id=7, edit=AsyncMock())
    )
    return interaction


async def _run(interaction: MagicMock, result: SyncResult) -> None:
    with patch(
        "src.cogs.commands.jobs.sync_jobs",
        new=AsyncMock(return_value=result),
    ) as sync_jobs:
        await JobsGroup.sync.callback(JobsGroup(), interaction)
    sync_jobs.assert_awaited_once()


async def test_sync_runs_when_the_channel_cannot_be_read():
    interaction = _interaction(fetch_message=AsyncMock(side_effect=_forbidden()))

    await _run(interaction, SyncResult(posted=3, skipped=1))

    # Progress falls back to the followup, which needs no channel permissions.
    followup = interaction.followup.send.return_value
    assert "Sync complete" in followup.edit.await_args.kwargs["content"]


async def test_the_real_message_is_preferred_when_it_can_be_had():
    # It outlives the interaction token, which a long sync can outrun.
    interaction = _interaction()

    await _run(interaction, SyncResult(posted=3, skipped=1))

    fetched = interaction.channel.fetch_message.return_value
    assert "Sync complete" in fetched.edit.await_args.kwargs["content"]
    interaction.followup.send.return_value.edit.assert_not_awaited()


async def test_a_failing_progress_edit_does_not_abandon_the_sync():
    message = MagicMock(id=7, edit=AsyncMock(side_effect=_forbidden()))
    interaction = _interaction(fetch_message=AsyncMock(return_value=message))

    # No exception: the sync ran and the failure stayed with the counter.
    await _run(interaction, SyncResult(posted=3, skipped=1))


@pytest.mark.parametrize("aborted", [True, False])
async def test_both_outcomes_are_reported(aborted):
    interaction = _interaction()

    await _run(interaction, SyncResult(posted=0, skipped=0, aborted=aborted))

    content = interaction.channel.fetch_message.return_value.edit.await_args.kwargs[
        "content"
    ]
    assert ("aborted" in content) is aborted
