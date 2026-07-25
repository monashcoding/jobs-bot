from src.backend.mongo.base import BaseCollection
from src.backend.mongo.client import MongoDatabase, mongo
from src.backend.mongo.collections import (
    ExampleDocument,
    ExampleDocumentCollection,
    example_document_col,
)
from src.backend.mongo.document import MongoDocument
from src.backend.mongo.triggers import ChangeEvent, ChangeStreamWatcher

__all__ = [
    "BaseCollection",
    "ChangeEvent",
    "ChangeStreamWatcher",
    "ExampleDocument",
    "ExampleDocumentCollection",
    "MongoDatabase",
    "MongoDocument",
    "example_document_col",
    "mongo",
]
