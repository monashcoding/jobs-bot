from __future__ import annotations

import logging
from typing import Final

import discord

_log: Final[logging.Logger] = logging.getLogger(__name__)

# Short enough to type, specific enough that it cannot be hit by accident or by
# a stray "yes". The rebuild deletes threads permanently, including whatever
# people said in them, so the confirmation has to be a deliberate act.
CONFIRM_PHRASE: Final[str] = "DELETE EVERYTHING"


class RebuildConfirmView(discord.ui.View):
    """Two-step confirmation for the destructive forum rebuild.

    Deliberately not persistent: the view dies with the interaction, so a
    confirmation left sitting in a channel cannot be pressed hours later by
    someone who has lost the context of what it was counting.

    Only the person who ran the command may confirm. The command is already
    admin-gated; this stops a second admin from pressing a button whose count
    they did not see.
    """

    def __init__(self, author_id: int, thread_count: int) -> None:
        super().__init__(timeout=120)
        self.author_id = author_id
        self.thread_count = thread_count
        self.confirmed: bool | None = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran this command can confirm it.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        # An expired confirmation must not stay pressable.
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content="Rebuild confirmation timed out. Nothing was deleted.",
                    view=self,
                )
            except Exception:  # noqa: BLE001
                _log.warning("Rebuild confirmation timed out; failed to edit message")

    @discord.ui.button(label="Delete everything", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"Confirmed. Deleting {self.thread_count} thread(s)...", view=self
        )
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Cancelled. Nothing was deleted.", view=self
        )
        self.stop()
