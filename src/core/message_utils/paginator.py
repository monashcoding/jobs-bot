import logging
from typing import Any

import discord
from discord import ButtonStyle
from discord.ui import Button, View, button
from discord.ui.item import Item
from discord.utils import get

_log = logging.getLogger(__name__)

PAGINATOR_ID_PREFIX = "paginator"


class PersistentPaginatorView(View):
    """Stub view registered at startup so buttons remain clickable after restart."""

    def __init__(self):
        super().__init__(timeout=None)

    @button(
        label="<<",
        style=ButtonStyle.primary,
        row=1,
        custom_id=f"{PAGINATOR_ID_PREFIX}:start",
    )
    async def on_start(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.send_message(
            "This paginator has expired.", ephemeral=True
        )

    @button(
        label="<", style=ButtonStyle.red, row=1, custom_id=f"{PAGINATOR_ID_PREFIX}:left"
    )
    async def on_left(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.send_message(
            "This paginator has expired.", ephemeral=True
        )

    @button(
        label=">>",
        style=ButtonStyle.primary,
        row=1,
        custom_id=f"{PAGINATOR_ID_PREFIX}:end",
    )
    async def on_end(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.send_message(
            "This paginator has expired.", ephemeral=True
        )

    @button(
        label=">",
        style=ButtonStyle.green,
        row=1,
        custom_id=f"{PAGINATOR_ID_PREFIX}:right",
    )
    async def on_right(self, interaction: discord.Interaction, btn: Button) -> None:
        await interaction.response.send_message(
            "This paginator has expired.", ephemeral=True
        )


class EmbedsPaginator(View):
    """Interactive paginator for a list of embeds. Buttons use persistent custom_ids
    so the view survives bot restarts (falls back to PersistentPaginatorView)."""

    def __init__(self, embeds: list[discord.Embed]) -> None:
        super().__init__(timeout=None)
        self.page_no = 0
        self.embeds = embeds

        self.indicator_button = get(self.children, custom_id="indicator")
        self.start_button = get(self.children, custom_id=f"{PAGINATOR_ID_PREFIX}:start")
        self.end_button = get(self.children, custom_id=f"{PAGINATOR_ID_PREFIX}:end")
        self.left_button = get(self.children, custom_id=f"{PAGINATOR_ID_PREFIX}:left")
        self.right_button = get(self.children, custom_id=f"{PAGINATOR_ID_PREFIX}:right")

        self.buttons_order: list[Button] = [
            self.start_button,
            self.left_button,
            self.indicator_button,
            self.right_button,
            self.end_button,
        ]

        self.update_page(0)

    def add_item(self, item: Item[Any]) -> None:
        if item in self.children:
            self.remove_item(item)
        return super().add_item(item)

    def _set_visible_buttons(self, visible: list[Button]) -> None:
        for item in self.buttons_order:
            if item in visible:
                self.add_item(item)
            else:
                self.remove_item(item)

    def update_page(self, page_no: int) -> discord.Embed:
        self.page_no = page_no
        self.indicator_button.label = f"{page_no + 1}/{len(self.embeds)}"

        if len(self.embeds) <= 1:
            self._set_visible_buttons([self.indicator_button])
        elif page_no == 0:
            self._set_visible_buttons(
                [self.indicator_button, self.right_button, self.end_button]
            )
        elif page_no == len(self.embeds) - 1:
            self._set_visible_buttons(
                [self.start_button, self.left_button, self.indicator_button]
            )
        else:
            self._set_visible_buttons(self.buttons_order)

        return self.embeds[page_no]

    async def go_to_page(self, interaction: discord.Interaction, page_no: int) -> None:
        try:
            await interaction.response.edit_message(
                embed=self.update_page(page_no), view=self
            )
        except (discord.Forbidden, discord.NotFound):
            _log.debug("Failed to edit paginator message %s", interaction.message.id)

    async def cycle_embeds(
        self, interaction: discord.Interaction, direction: int
    ) -> None:
        new_page = self.page_no + direction
        if new_page < 0 or new_page >= len(self.embeds):
            return await interaction.response.defer()
        await self.go_to_page(interaction, new_page)

    @button(
        label="<<",
        style=ButtonStyle.primary,
        row=1,
        custom_id=f"{PAGINATOR_ID_PREFIX}:start",
    )
    async def on_start(self, interaction: discord.Interaction, btn: Button) -> None:
        await self.go_to_page(interaction, 0)

    @button(
        label="<", style=ButtonStyle.red, row=1, custom_id=f"{PAGINATOR_ID_PREFIX}:left"
    )
    async def on_left(self, interaction: discord.Interaction, btn: Button) -> None:
        await self.cycle_embeds(interaction, -1)

    @button(
        label="NaN/NaN",
        style=ButtonStyle.grey,
        row=1,
        disabled=True,
        custom_id="indicator",
    )
    async def on_indicator(self, interaction: discord.Interaction, btn: Button) -> None:
        pass

    @button(
        label=">",
        style=ButtonStyle.green,
        row=1,
        custom_id=f"{PAGINATOR_ID_PREFIX}:right",
    )
    async def on_right(self, interaction: discord.Interaction, btn: Button) -> None:
        await self.cycle_embeds(interaction, 1)

    @button(
        label=">>",
        style=ButtonStyle.primary,
        row=1,
        custom_id=f"{PAGINATOR_ID_PREFIX}:end",
    )
    async def on_end(self, interaction: discord.Interaction, btn: Button) -> None:
        await self.go_to_page(interaction, len(self.embeds) - 1)
