import discord
from discord import app_commands
from discord.ext import commands

from src.backend.sql.models import ExampleRecord
from src.backend.sql.tables import example_record


class Example(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="example-add", description="Store an example record")
    async def example_add(self, interaction: discord.Interaction, value: str):
        record = await example_record.upsert(
            ExampleRecord(user_id=interaction.user.id, value=value)
        )
        await interaction.response.send_message(
            f"Stored record #{record.id}: `{record.value}`", ephemeral=True
        )

    @app_commands.command(name="example-list", description="List your example records")
    async def example_list(self, interaction: discord.Interaction):
        records = await example_record.get_by_user_id(interaction.user.id)
        if not records:
            await interaction.response.send_message("No records found.", ephemeral=True)
            return
        lines = [f"#{r.id}: `{r.value}`" for r in records]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Example(bot))
