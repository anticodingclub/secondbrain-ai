"""Local object storage."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.core.exceptions import ObjectNotFoundError
from app.services.storage.local import LocalObjectStorage, sanitize_extension


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    for part in parts:
        yield part


@pytest.fixture
def storage(tmp_path: Path) -> LocalObjectStorage:
    return LocalObjectStorage(tmp_path)


async def test_put_returns_size_and_hash(storage: LocalObjectStorage) -> None:
    payload = b"the quick brown fox"

    stored = await storage.put(owner_id=uuid.uuid4(), filename="notes.txt", stream=chunks(payload))

    assert stored.size_bytes == len(payload)
    assert stored.content_hash == hashlib.sha256(payload).hexdigest()


async def test_hash_is_computed_across_chunk_boundaries(storage: LocalObjectStorage) -> None:
    """A hash accumulated per chunk must equal one over the whole payload."""
    stored = await storage.put(
        owner_id=uuid.uuid4(), filename="a.txt", stream=chunks(b"abc", b"def", b"ghi")
    )

    assert stored.content_hash == hashlib.sha256(b"abcdefghi").hexdigest()


async def test_round_trips_content(storage: LocalObjectStorage) -> None:
    payload = b"x" * (3 * 1024 * 1024)  # spans several read buffers
    stored = await storage.put(owner_id=uuid.uuid4(), filename="big.bin", stream=chunks(payload))

    read_back = b"".join([part async for part in await storage.open(stored.key)])

    assert read_back == payload


async def test_keys_are_generated_not_derived_from_the_filename(
    storage: LocalObjectStorage, tmp_path: Path
) -> None:
    """A hostile filename must not influence where bytes land."""
    owner = uuid.uuid4()

    stored = await storage.put(
        owner_id=owner, filename="../../../etc/passwd", stream=chunks(b"nope")
    )

    assert ".." not in stored.key
    assert stored.key.startswith(f"{owner}/")
    written = (tmp_path / stored.key).resolve()
    assert written.is_relative_to(tmp_path.resolve())
    assert written.exists()


async def test_two_uploads_of_identical_bytes_get_distinct_keys(
    storage: LocalObjectStorage,
) -> None:
    """Keys are random, so storage never collides; dedupe is the service's job."""
    owner = uuid.uuid4()
    first = await storage.put(owner_id=owner, filename="a.txt", stream=chunks(b"same"))
    second = await storage.put(owner_id=owner, filename="a.txt", stream=chunks(b"same"))

    assert first.key != second.key
    assert first.content_hash == second.content_hash


async def test_owners_are_partitioned_on_disk(storage: LocalObjectStorage) -> None:
    ada, grace = uuid.uuid4(), uuid.uuid4()

    ada_object = await storage.put(owner_id=ada, filename="a.txt", stream=chunks(b"a"))
    grace_object = await storage.put(owner_id=grace, filename="a.txt", stream=chunks(b"g"))

    assert ada_object.key.startswith(f"{ada}/")
    assert grace_object.key.startswith(f"{grace}/")


async def test_failed_stream_leaves_no_partial_file(
    storage: LocalObjectStorage, tmp_path: Path
) -> None:
    """A half-written file must never survive to be mistaken for a whole one."""

    async def failing() -> AsyncIterator[bytes]:
        yield b"first chunk"
        raise RuntimeError("client vanished")

    with pytest.raises(RuntimeError):
        await storage.put(owner_id=uuid.uuid4(), filename="doomed.txt", stream=failing())

    written = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert written == []


async def test_delete_removes_the_object(storage: LocalObjectStorage) -> None:
    stored = await storage.put(owner_id=uuid.uuid4(), filename="a.txt", stream=chunks(b"x"))

    assert await storage.delete(stored.key) is True
    assert await storage.exists(stored.key) is False


async def test_delete_is_idempotent(storage: LocalObjectStorage) -> None:
    stored = await storage.put(owner_id=uuid.uuid4(), filename="a.txt", stream=chunks(b"x"))
    await storage.delete(stored.key)

    assert await storage.delete(stored.key) is False


async def test_open_missing_object_raises_before_streaming(storage: LocalObjectStorage) -> None:
    """The error must surface before a response body has started."""
    with pytest.raises(ObjectNotFoundError):
        await storage.open(f"{uuid.uuid4()}/ab/cd/deadbeef.txt")


async def test_keys_that_escape_the_root_are_rejected(storage: LocalObjectStorage) -> None:
    with pytest.raises(ValueError, match="escapes the storage root"):
        await storage.exists("../../../../etc/passwd")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("report.PDF", ".pdf"),
        ("archive.tar.gz", ".gz"),
        ("no-extension", ""),
        ("evil.php%00", ""),
        ("x." + "a" * 40, ""),
        (".gitignore", ""),
    ],
)
def test_extension_sanitising(filename: str, expected: str) -> None:
    assert sanitize_extension(filename) == expected
