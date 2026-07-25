"""Example MongoDB change stream watcher cog.

Rename this file (remove the leading underscore) to activate it.
Requires MongoDB to be configured (MONGODB_URI set and mongo.init() called in bot.py)
and a replica set or Atlas cluster (change streams are not supported on standalone nodes).
"""

import logging
from typing import ClassVar

from discord.ext import commands

from src.backend.mongo.collections import example_document_col
from src.backend.mongo.triggers import ChangeEvent, ChangeStreamWatcher, Operation

_log = logging.getLogger(__name__)


class ExampleMongoWatcher(ChangeStreamWatcher):
    """Logs every insert/update/replace on the example_documents collection."""

    collection = example_document_col
    operations: ClassVar[list[Operation]] = [
        Operation.INSERT,
        Operation.UPDATE,
        Operation.REPLACE,
    ]

    async def on_change(self, event: ChangeEvent) -> None:
        _log.info(
            "Change detected: op=%s id=%s doc=%s",
            event.operation,
            event.document_id,
            event.full_document,
        )

    async def on_delete(self, document_id: str) -> None:
        _log.info("Document deleted: id=%s", document_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ExampleMongoWatcher(bot))
