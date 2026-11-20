"""Detector modules.

Importing this package registers every module with the registry. Add a new
detector by creating a module here and decorating the class with
``@register``; nothing else needs to change.
"""

from . import (          # noqa: F401
    interface,
    observability,
    presence,
    corpus,
    retrieval,
    routing,
    chunking,
    index,
    generation,
    opsec,
    errors,
    embedding,
)
