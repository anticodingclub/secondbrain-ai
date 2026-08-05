"""Filesystem-backed object storage."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles
import aiofiles.os

from app.core.exceptions import ObjectNotFoundError
from app.core.logging import get_logger
from app.services.storage.base import ObjectStorage, StoredObject

logger = get_logger(__name__)

#: 1 MiB. Large enough that syscall overhead is irrelevant, small enough that a
#: hundred concurrent uploads do not add up to meaningful memory.
CHUNK_SIZE = 1024 * 1024


class LocalObjectStorage(ObjectStorage):
    """Stores objects under ``<root>/<owner>/<aa>/<bb>/<uuid><ext>``.

    Keys are *generated*, never derived from user input, which removes path
    traversal as a class of bug rather than trying to sanitise it away — a
    filename of ``../../etc/passwd`` simply never reaches the filesystem.

    The two nested hex levels keep directory sizes sane: ext4 and NTFS both
    degrade badly at a few hundred thousand entries in one directory, and this
    project is specified to hold 100k+ documents.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    async def put(
        self, *, owner_id: uuid.UUID, filename: str, stream: AsyncIterator[bytes]
    ) -> StoredObject:
        key = self._generate_key(owner_id, filename)
        path = self._path_for(key)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)

        digest = hashlib.sha256()
        size = 0

        try:
            async with aiofiles.open(path, "wb") as handle:
                async for chunk in stream:
                    if not chunk:
                        continue
                    digest.update(chunk)
                    size += len(chunk)
                    await handle.write(chunk)
        except BaseException:
            # Includes cancellation: a client that disconnects mid-upload must
            # not leave a half-written file behind to be mistaken for a
            # complete one.
            await self._unlink_quietly(path)
            raise

        logger.debug("object_stored", key=key, size_bytes=size)
        return StoredObject(key=key, size_bytes=size, content_hash=digest.hexdigest())

    async def open(self, key: str) -> AsyncIterator[bytes]:
        path = self._path_for(key)
        if not await aiofiles.os.path.exists(path):
            logger.error("storage_object_missing", key=key)
            raise ObjectNotFoundError()

        async def iterator() -> AsyncIterator[bytes]:
            async with aiofiles.open(path, "rb") as handle:
                while chunk := await handle.read(CHUNK_SIZE):
                    yield chunk

        return iterator()

    async def put_derived(self, *, source_key: str, suffix: str, data: bytes) -> str:
        key = f"{source_key}{suffix}"
        path = self._path_for(key)
        await aiofiles.os.makedirs(path.parent, exist_ok=True)

        try:
            async with aiofiles.open(path, "wb") as handle:
                await handle.write(data)
        except BaseException:
            await self._unlink_quietly(path)
            raise

        logger.debug("derived_object_stored", key=key, size_bytes=len(data))
        return key

    async def delete(self, key: str) -> bool:
        return await self._unlink_quietly(self._path_for(key))

    async def delete_prefix(self, prefix: str) -> int:
        """Delete the object and its siblings sharing the same key prefix.

        Derived artifacts are stored as `<key><suffix>` in the same directory,
        so a prefix match over that one directory finds them all without
        walking the tree.
        """
        base = self._path_for(prefix)
        removed = 0

        try:
            entries = await aiofiles.os.listdir(base.parent)
        except (FileNotFoundError, NotADirectoryError):
            return 0

        for entry in entries:
            if entry.startswith(base.name) and await self._unlink_quietly(base.parent / entry):
                removed += 1
        return removed

    async def exists(self, key: str) -> bool:
        return bool(await aiofiles.os.path.exists(self._path_for(key)))

    async def size(self, key: str) -> int:
        path = self._path_for(key)
        if not await aiofiles.os.path.exists(path):
            raise ObjectNotFoundError()
        return (await aiofiles.os.stat(path)).st_size

    # ── Internals ────────────────────────────────────────────────────────

    def _generate_key(self, owner_id: uuid.UUID, filename: str) -> str:
        object_id = uuid.uuid4().hex
        suffix = sanitize_extension(filename)
        return f"{owner_id}/{object_id[:2]}/{object_id[2:4]}/{object_id}{suffix}"

    def _path_for(self, key: str) -> Path:
        path = (self._root / key).resolve()
        # Defence in depth. Keys are generated, so this should be unreachable —
        # but a bad key from a corrupted row must not be able to read
        # /etc/shadow, and the check is far cheaper than the consequence.
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError(f"Storage key escapes the storage root: {key!r}")
        return path

    @staticmethod
    async def _unlink_quietly(path: Path) -> bool:
        try:
            await aiofiles.os.remove(path)
        except FileNotFoundError:
            return False
        except OSError as exc:
            logger.warning("object_delete_failed", path=str(path), error=str(exc))
            return False
        return True


def sanitize_extension(filename: str) -> str:
    """The extension, lowercased, or "" if there is not a plausible one.

    Kept only so stored files remain recognisable to a human browsing the data
    directory; nothing depends on it for correctness. Anything long or
    non-alphanumeric is dropped rather than cleaned, because a "clever"
    sanitiser is exactly where traversal bugs hide.
    """
    suffix = Path(filename).suffix.lower()
    if 1 < len(suffix) <= 16 and suffix[1:].isalnum():
        return suffix
    return ""
