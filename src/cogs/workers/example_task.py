import logging

from discord.ext import commands, tasks

_log = logging.getLogger(__name__)


class ExampleTask(commands.Cog):
    """Background task that runs on a fixed interval."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.task.start()

    def cog_unload(self):
        self.task.cancel()

    @tasks.loop(hours=1)
    async def task(self):
        _log.info("Example background task running")
        # Add your recurring logic here

    @task.before_loop
    async def before_task(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ExampleTask(bot))
