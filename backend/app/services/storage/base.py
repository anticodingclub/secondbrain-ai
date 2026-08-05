"""Object storage interface.

Deliberately modelled on the *narrow* subset of S3 semantics we actually need —
put a stream, open a stream, delete, exists — so the local implementation is not
a leaky simulation of a filesystem that S3 later fails to honour. Notably absent:
listing, renaming, appending and random writes, none of which S3 does cheaply.

Callers deal in opaque **storage keys**, never filesystem paths.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    #: SHA-256 of the bytes as written, computed during the streaming write so
    #: the data is never read a second time to hash it.
    content_hash: str


class ObjectStorage(ABC):
    """Where uploaded bytes live."""

    @abstractmethod
    async def put(
        self, *, owner_id: uuid.UUID, filename: str, stream: AsyncIterator[bytes]
    ) -> StoredObject:
        """Persist a stream and return its key, size and hash.

        Implementations must stream: a 2 GB upload buffered in memory is an
        outage. They must also clean up partial writes if the stream fails.
        """

    @abstractmethod
    async def open(self, key: str) -> AsyncIterator[bytes]:
        """Stream an object back out. Raises `ObjectNotFoundError` if missing.

        Async because the existence check must happen before the caller starts
        iterating — a missing object should raise here, not halfway through a
        response body that has already begun streaming to the client.
        """

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Remove an object. Returns False if it was already gone."""

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def size(self, key: str) -> int:
        """Bytes on disk. Used to detect storage that has drifted from the DB."""
