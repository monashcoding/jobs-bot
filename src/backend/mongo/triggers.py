from __future__ import annotations

import asyncio
import logging
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, Generic, TypeVar

from discord.ext import commands
from discord.ext.commands import CogMeta
from pymongo.errors import OperationFailure, PyMongoError

from src.backend.mongo.base import BaseCollection

_log = logging.getLogger(__name__)

T = TypeVar("T")


class Operation(StrEnum):
    INSERT = "insert"
    UPDATE = "update"
    REPLACE = "replace"
    DELETE = "delete"


@dataclass
class ChangeEvent(Generic[T]):
    """Parsed MongoDB change stream event."""

    operation: Operation
    document_id: str
    full_document: T | None
    raw: dict = field(repr=False)

    @classmethod
    def from_raw(cls, raw: dict, model: type[T]) -> ChangeEvent[T]:
        from bson import ObjectId

        op = Operation(raw.get("operationType", ""))
        doc_id = str(raw.get("documentKey", {}).get("_id", ""))
        full = None
        if raw.get("fullDocument") is not None:
            fd = dict(raw["fullDocument"])
            if "_id" in fd and isinstance(fd["_id"], ObjectId):
                fd["_id"] = str(fd["_id"])
            full = model.model_validate(fd)
        return cls(operation=op, document_id=doc_id, full_document=full, raw=raw)


class _CogABCMeta(CogMeta, ABCMeta):
    """Combined metaclass that merges discord.py's CogMeta with ABCMeta.

    Allows ChangeStreamWatcher to be a proper abstract base class while
    still registering correctly as a discord.py Cog.
    """


class ChangeStreamWatcher(commands.Cog, metaclass=_CogABCMeta):
    """Abstract base cog for consuming MongoDB change streams.

    Subclasses must:
    - Set the `collection` class attribute to a BaseCollection instance.
    - Implement `on_change`.

    Optional overrides:
    - `operations`: list of Operation values to filter on.
    - `full_document`: Motor full_document option (default "updateLookup").

    The watcher task starts when the cog loads and restarts automatically on
    transient errors with exponential backoff (cap 60s).
    """

    collection: BaseCollection
    operations: ClassVar[list[Operation]] = [
        Operation.INSERT,
        Operation.UPDATE,
        Operation.REPLACE,
        Operation.DELETE,
    ]
    full_document: str = "updateLookup"

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._watch_task: asyncio.Task[Any] | None = None

    async def cog_load(self) -> None:
        self._watch_task = asyncio.create_task(self._run_watcher())

    def cog_unload(self) -> None:
        if self._watch_task:
            self._watch_task.cancel()

    @abstractmethod
    async def on_change(self, event: ChangeEvent) -> None:
        """React to a change stream event. Must be implemented by subclasses."""

    @abstractmethod
    async def on_delete(self, document_id: str) -> None:
        """Called when a document is deleted. Must be implemented by subclasses.

        Receives only the document_id because the document no longer exists
        at the time the event is processed.
        """

    async def _run_watcher(self) -> None:
        await self.bot.wait_until_ready()
        pipeline = [
            {"$match": {"operationType": {"$in": [op.value for op in self.operations]}}}
        ]
        backoff = 1.0
        while True:
            try:
                async with self.collection.watch(
                    pipeline=pipeline, full_document=self.full_document
                ) as stream:
                    backoff = 1.0  # reset on successful connection
                    async for raw in stream:
                        event = ChangeEvent.from_raw(raw, self.collection.model)
                        try:
                            if event.operation is Operation.DELETE:
                                await self.on_delete(event.document_id)
                            else:
                                await self.on_change(event)
                        except Exception:  # noqa: BLE001
                            _log.exception("on_change raised for event %s", event)
            except asyncio.CancelledError:
                return
            except (OperationFailure, PyMongoError) as exc:
                _log.warning(
                    "Change stream error (%s), retrying in %.1fs", exc, backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except Exception:  # noqa: BLE001
                _log.exception("Unexpected error in change stream watcher")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
