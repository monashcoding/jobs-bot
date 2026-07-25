from src.backend.mongo.base import BaseCollection
from src.backend.mongo.client import MongoDatabase, mongo
from src.backend.mongo.collections import (
    ExampleDocument,
    ExampleDocumentCollection,
    JobDocument,
    JobDocumentCollection,
    example_document_col,
    job_col,
)
from src.backend.mongo.document import MongoDocument
from src.backend.mongo.triggers import ChangeEvent, ChangeStreamWatcher

__all__ = [
    "BaseCollection",
    "ChangeEvent",
    "ChangeStreamWatcher",
    "ExampleDocument",
    "ExampleDocumentCollection",
    "JobDocument",
    "JobDocumentCollection",
    "MongoDatabase",
    "MongoDocument",
    "example_document_col",
    "job_col",
    "mongo",
]
