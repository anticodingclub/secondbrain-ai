"""Document upload and management through the real ASGI app."""

from __future__ import annotations

import hashlib
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"

PDF_BYTES = b"%PDF-1.7\n" + b"stand-in for a real PDF body\n" * 8
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def sign_up(client: AsyncClient, email: str = "ada@example.com") -> str:
    response = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Ada"},
    )
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def upload(
    client: AsyncClient,
    token: str,
    *,
    filename: str = "notes.txt",
    content: bytes = b"OAuth notes: we chose PKCE.",
    content_type: str = "text/plain",
):
    return await client.post(
        f"{PREFIX}/documents/upload",
        headers=bearer(token),
        files={"file": (filename, content, content_type)},
    )


# ── Upload ───────────────────────────────────────────────────────────────────


async def test_upload_returns_the_stored_document(client: AsyncClient) -> None:
    token = await sign_up(client)

    response = await upload(client, token, filename="oauth-notes.md", content=b"# OAuth\nPKCE.")

    assert response.status_code == 201
    body = response.json()
    assert body["was_duplicate"] is False
    document = body["document"]
    assert document["original_filename"] == "oauth-notes.md"
    assert document["extension"] == "md"
    assert document["mime_type"] == "text/markdown"
    assert document["status"] == "pending"
    assert document["size_bytes"] == len(b"# OAuth\nPKCE.")


async def test_content_hash_is_the_sha256_of_the_bytes(client: AsyncClient) -> None:
    token = await sign_up(client)
    payload = b"deterministic content"

    response = await upload(client, token, content=payload)

    assert response.json()["document"]["content_hash"] == hashlib.sha256(payload).hexdigest()


async def test_title_is_humanised_from_the_filename(client: AsyncClient) -> None:
    token = await sign_up(client)

    response = await upload(client, token, filename="internship_offer-letter.txt")

    assert response.json()["document"]["title"] == "internship offer letter"


async def test_uploading_the_same_bytes_twice_deduplicates(client: AsyncClient) -> None:
    token = await sign_up(client)
    payload = b"identical bytes"

    first = await upload(client, token, filename="a.txt", content=payload)
    second = await upload(client, token, filename="a-copy.txt", content=payload)

    assert first.json()["was_duplicate"] is False
    assert second.json()["was_duplicate"] is True
    # Same row, not a second copy.
    assert second.json()["document"]["id"] == first.json()["document"]["id"]

    listing = await client.get(f"{PREFIX}/documents", headers=bearer(token))
    assert listing.json()["total"] == 1


async def test_two_users_may_each_own_the_same_file(client: AsyncClient) -> None:
    """Dedupe is per-owner: sharing a PDF must not be mistaken for a duplicate."""
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    payload = b"a widely shared handbook"

    assert (await upload(client, ada, content=payload)).json()["was_duplicate"] is False
    assert (await upload(client, grace, content=payload)).json()["was_duplicate"] is False


async def test_rejects_unsupported_file_types(client: AsyncClient) -> None:
    token = await sign_up(client)

    response = await upload(client, token, filename="virus.exe", content=b"MZ\x90\x00")

    assert response.status_code == 415
    assert response.json()["error"] == "unsupported_media_type"


async def test_rejects_a_file_whose_bytes_contradict_its_extension(
    client: AsyncClient,
) -> None:
    """Renaming an executable to .pdf must not get it indexed."""
    token = await sign_up(client)

    response = await upload(client, token, filename="payload.pdf", content=b"MZ\x90\x00" * 20)

    assert response.status_code == 415
    assert "valid pdf" in response.json()["message"].lower()


async def test_accepts_a_genuine_pdf(client: AsyncClient) -> None:
    token = await sign_up(client)

    response = await upload(client, token, filename="report.pdf", content=PDF_BYTES)

    assert response.status_code == 201
    assert response.json()["document"]["mime_type"] == "application/pdf"


async def test_accepts_a_genuine_png(client: AsyncClient) -> None:
    token = await sign_up(client)

    response = await upload(client, token, filename="scan.png", content=PNG_BYTES)

    assert response.status_code == 201


async def test_rejects_an_empty_file(client: AsyncClient) -> None:
    token = await sign_up(client)

    response = await upload(client, token, content=b"")

    assert response.status_code == 415


async def test_a_hostile_filename_cannot_escape_storage(client: AsyncClient) -> None:
    token = await sign_up(client)

    response = await upload(client, token, filename="../../../etc/passwd.txt")

    assert response.status_code == 201
    # The name is preserved for display, but never used as a path.
    assert response.json()["document"]["original_filename"] == "../../../etc/passwd.txt"


async def test_upload_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        f"{PREFIX}/documents/upload", files={"file": ("a.txt", b"x", "text/plain")}
    )
    assert response.status_code == 401


# ── Listing and filtering ────────────────────────────────────────────────────


async def test_list_is_scoped_to_the_owner(client: AsyncClient) -> None:
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")

    await upload(client, ada, filename="ada-notes.txt", content=b"ada's private notes")

    seen_by_grace = await client.get(f"{PREFIX}/documents", headers=bearer(grace))

    assert seen_by_grace.json()["total"] == 0
    assert seen_by_grace.json()["items"] == []


async def test_list_is_newest_first(client: AsyncClient) -> None:
    token = await sign_up(client)
    for name in ("first.txt", "second.txt", "third.txt"):
        await upload(client, token, filename=name, content=f"content of {name}".encode())

    items = (await client.get(f"{PREFIX}/documents", headers=bearer(token))).json()["items"]

    assert [item["original_filename"] for item in items] == [
        "third.txt",
        "second.txt",
        "first.txt",
    ]


async def test_list_paginates(client: AsyncClient) -> None:
    token = await sign_up(client)
    for index in range(5):
        await upload(client, token, filename=f"doc{index}.txt", content=f"body {index}".encode())

    page = await client.get(
        f"{PREFIX}/documents", headers=bearer(token), params={"limit": 2, "offset": 2}
    )

    body = page.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["offset"] == 2


async def test_filter_by_extension(client: AsyncClient) -> None:
    token = await sign_up(client)
    await upload(client, token, filename="a.txt", content=b"text file")
    await upload(client, token, filename="b.pdf", content=PDF_BYTES)

    filtered = await client.get(
        f"{PREFIX}/documents", headers=bearer(token), params={"extension": "pdf"}
    )

    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["extension"] == "pdf"


async def test_search_matches_title_and_filename(client: AsyncClient) -> None:
    token = await sign_up(client)
    await upload(client, token, filename="internship-offer.txt", content=b"offer details")
    await upload(client, token, filename="grocery-list.txt", content=b"eggs, milk")

    found = await client.get(
        f"{PREFIX}/documents", headers=bearer(token), params={"search": "internship"}
    )

    assert found.json()["total"] == 1
    assert found.json()["items"][0]["original_filename"] == "internship-offer.txt"


async def test_usage_reports_document_count_and_bytes(client: AsyncClient) -> None:
    token = await sign_up(client)
    await upload(client, token, filename="a.txt", content=b"12345")
    await upload(client, token, filename="b.txt", content=b"678")

    usage = (await client.get(f"{PREFIX}/documents/usage", headers=bearer(token))).json()

    assert usage["document_count"] == 2
    assert usage["total_bytes"] == 8
    assert usage["max_upload_bytes"] > 0


# ── Retrieval and download ───────────────────────────────────────────────────


async def test_get_one_document(client: AsyncClient) -> None:
    token = await sign_up(client)
    document_id = (await upload(client, token)).json()["document"]["id"]

    response = await client.get(f"{PREFIX}/documents/{document_id}", headers=bearer(token))

    assert response.status_code == 200
    assert response.json()["id"] == document_id


async def test_download_returns_the_original_bytes(client: AsyncClient) -> None:
    token = await sign_up(client)
    payload = b"# OAuth notes\nWe chose PKCE for the mobile client."
    document_id = (await upload(client, token, filename="oauth.md", content=payload)).json()[
        "document"
    ]["id"]

    response = await client.get(f"{PREFIX}/documents/{document_id}/content", headers=bearer(token))

    assert response.status_code == 200
    assert response.content == payload


async def test_another_user_cannot_read_a_document(client: AsyncClient) -> None:
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    document_id = (await upload(client, ada)).json()["document"]["id"]

    assert (
        await client.get(f"{PREFIX}/documents/{document_id}", headers=bearer(grace))
    ).status_code == 404
    assert (
        await client.get(f"{PREFIX}/documents/{document_id}/content", headers=bearer(grace))
    ).status_code == 404


async def test_missing_and_forbidden_are_indistinguishable(client: AsyncClient) -> None:
    """Both must be 404, or the endpoint leaks which ids exist."""
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    owned_by_ada = (await upload(client, ada)).json()["document"]["id"]

    forbidden = await client.get(f"{PREFIX}/documents/{owned_by_ada}", headers=bearer(grace))
    missing = await client.get(f"{PREFIX}/documents/{uuid.uuid4()}", headers=bearer(grace))

    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json()["message"] == missing.json()["message"]


# ── Deletion ─────────────────────────────────────────────────────────────────


async def test_delete_removes_the_document(client: AsyncClient) -> None:
    token = await sign_up(client)
    document_id = (await upload(client, token)).json()["document"]["id"]

    assert (
        await client.delete(f"{PREFIX}/documents/{document_id}", headers=bearer(token))
    ).status_code == 204
    assert (
        await client.get(f"{PREFIX}/documents/{document_id}", headers=bearer(token))
    ).status_code == 404


async def test_deleting_frees_the_content_hash_for_reupload(client: AsyncClient) -> None:
    """After deletion the same file must upload cleanly, not trip dedupe."""
    token = await sign_up(client)
    payload = b"some content"
    document_id = (await upload(client, token, content=payload)).json()["document"]["id"]

    await client.delete(f"{PREFIX}/documents/{document_id}", headers=bearer(token))
    again = await upload(client, token, content=payload)

    assert again.status_code == 201
    assert again.json()["was_duplicate"] is False


async def test_another_user_cannot_delete_a_document(client: AsyncClient) -> None:
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    document_id = (await upload(client, ada)).json()["document"]["id"]

    assert (
        await client.delete(f"{PREFIX}/documents/{document_id}", headers=bearer(grace))
    ).status_code == 404
    # ...and it is genuinely still there for its owner.
    assert (
        await client.get(f"{PREFIX}/documents/{document_id}", headers=bearer(ada))
    ).status_code == 200
