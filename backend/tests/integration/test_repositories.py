"""Repository import.

Clones a git repository created on disk by the test itself. Cloning from
GitHub would make the suite depend on the network, on a third party's uptime,
and on a repository whose contents can change underneath the assertions.
`git clone` treats a local path exactly like a remote, so the code under test
is the same either way.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.repositories import git_is_available, parse_repository
from app.services.repositories.git import RepositoryError

pytestmark = [pytest.mark.integration, pytest.mark.slow]

PREFIX = "/api/v1"

pytest.importorskip("pytest_asyncio")

skip_without_git = pytest.mark.skipif(not git_is_available(), reason="git is not installed")


@pytest.fixture
def sample_repository(tmp_path: Path) -> Path:
    """A real git repository holding source, docs, and things to skip."""
    root = tmp_path / "sample-project"
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "dist").mkdir()

    (root / "README.md").write_text(
        "# Sample Project\n\n## Authentication\n\n"
        "Authentication uses OAuth 2.0 with PKCE for public clients.\n",
        encoding="utf-8",
    )
    (root / "src" / "auth.py").write_text(
        "def authenticate(user):\n"
        '    """Verify a user password."""\n'
        "    return verify(user.password)\n",
        encoding="utf-8",
    )
    (root / "src" / "server.ts").write_text(
        "export function createServer() {\n  return app.listen(8000);\n}\n",
        encoding="utf-8",
    )

    # Things the walker must leave out.
    (root / "package-lock.json").write_text('{"lockfileVersion": 3}', encoding="utf-8")
    (root / "node_modules" / "left-pad" / "index.js").write_text(
        "module.exports = function () {};", encoding="utf-8"
    )
    (root / "dist" / "bundle.min.js").write_text("!function(){}();", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-qm", "init"],
        cwd=root,
        check=True,
    )
    return root


async def sign_up(client: AsyncClient, email: str = "ada@example.com") -> str:
    response = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Ada"},
    )
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Parsing references ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "reference",
    [
        "https://github.com/tiangolo/fastapi",
        "https://github.com/tiangolo/fastapi.git",
        "https://www.github.com/tiangolo/fastapi/",
        "git@github.com:tiangolo/fastapi.git",
        "tiangolo/fastapi",
    ],
)
def test_every_form_people_paste_is_accepted(reference: str) -> None:
    ref = parse_repository(reference)

    assert ref.owner == "tiangolo"
    assert ref.name == "fastapi"
    assert ref.clone_url == "https://github.com/tiangolo/fastapi.git"


@pytest.mark.parametrize(
    "reference",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://gitlab.com/owner/name",
        "https://internal.corp/secret.git",
        "not a url at all",
        "ssh://root@10.0.0.1/repo",
    ],
)
def test_non_github_urls_are_refused(reference: str) -> None:
    """Cloning an arbitrary URL on a user's behalf is a server-side request
    forgery primitive — it would let anyone point the server at an internal
    host and read the outcome from the error message."""
    with pytest.raises(RepositoryError):
        parse_repository(reference)


# ── Walking ──────────────────────────────────────────────────────────────────


@skip_without_git
def test_generated_and_vendored_trees_are_skipped(sample_repository: Path) -> None:
    """A search for "authenticate" must not return forty copies of a vendored
    library."""
    from app.services.repositories import walk_repository

    result = walk_repository(sample_repository)
    names = {path.name for path in result.files}

    assert "README.md" in names
    assert "auth.py" in names
    assert "server.ts" in names

    assert "index.js" not in names, "node_modules was walked"
    assert "package-lock.json" not in names, "lockfile was imported"
    assert "bundle.min.js" not in names, "minified bundle was imported"
    assert result.skipped > 0


@skip_without_git
def test_binary_files_are_skipped(sample_repository: Path) -> None:
    from app.services.repositories import walk_repository

    result = walk_repository(sample_repository)

    assert "logo.png" not in {path.name for path in result.files}


# ── Importing ────────────────────────────────────────────────────────────────


@skip_without_git
async def test_importing_a_repository_indexes_its_files(
    client: AsyncClient, sample_repository: Path
) -> None:
    token = await sign_up(client)

    response = await client.post(
        f"{PREFIX}/repositories",
        headers=bearer(token),
        json={"repository": str(sample_repository)},
    )
    assert response.status_code == 202, response.text
    repository_id = response.json()["id"]

    detail = (
        await client.get(f"{PREFIX}/repositories/{repository_id}", headers=bearer(token))
    ).json()

    assert detail["status"] == "ready"
    assert detail["file_count"] == 3
    assert detail["skipped_count"] > 0
    assert detail["commit_sha"]


@skip_without_git
async def test_imported_code_is_searchable(client: AsyncClient, sample_repository: Path) -> None:
    """The question the brief asks by name: "Where is authentication
    implemented?"."""
    token = await sign_up(client)
    await client.post(
        f"{PREFIX}/repositories",
        headers=bearer(token),
        json={"repository": str(sample_repository)},
    )

    results = await client.post(
        f"{PREFIX}/search",
        headers=bearer(token),
        json={"query": "Where is authentication implemented?"},
    )

    hits = results.json()["hits"]
    assert hits, "imported code was not searchable"
    assert any("auth" in hit["filename"].lower() for hit in hits[:3])


@skip_without_git
async def test_documents_keep_their_path_not_just_a_filename(
    client: AsyncClient, sample_repository: Path
) -> None:
    """Forty files called `index.ts` are indistinguishable by name alone."""
    token = await sign_up(client)
    await client.post(
        f"{PREFIX}/repositories",
        headers=bearer(token),
        json={"repository": str(sample_repository)},
    )

    documents = (await client.get(f"{PREFIX}/documents", headers=bearer(token))).json()
    filenames = {item["original_filename"] for item in documents["items"]}

    assert "src/auth.py" in filenames
    assert "src/server.ts" in filenames


@skip_without_git
async def test_imported_files_belong_to_a_collection(
    client: AsyncClient, sample_repository: Path
) -> None:
    """So the repository can be filtered and chatted with as a unit."""
    token = await sign_up(client)
    response = await client.post(
        f"{PREFIX}/repositories",
        headers=bearer(token),
        json={"repository": str(sample_repository)},
    )

    collection_id = (
        response.json()["collection_id"]
        or (
            await client.get(
                f"{PREFIX}/repositories/{response.json()['id']}", headers=bearer(token)
            )
        ).json()["collection_id"]
    )

    assert collection_id
    documents = (await client.get(f"{PREFIX}/documents", headers=bearer(token))).json()
    assert all(item["collection_id"] == collection_id for item in documents["items"])


@skip_without_git
async def test_re_syncing_does_not_duplicate_unchanged_files(
    client: AsyncClient, sample_repository: Path
) -> None:
    """Content-hash dedupe means an unchanged repository costs a clone and
    nothing else."""
    token = await sign_up(client)
    first = await client.post(
        f"{PREFIX}/repositories",
        headers=bearer(token),
        json={"repository": str(sample_repository)},
    )
    repository_id = first.json()["id"]

    before = (await client.get(f"{PREFIX}/documents", headers=bearer(token))).json()["total"]

    await client.post(f"{PREFIX}/repositories/{repository_id}/sync", headers=bearer(token))

    after = (await client.get(f"{PREFIX}/documents", headers=bearer(token))).json()["total"]
    assert after == before


# ── Failure and isolation ────────────────────────────────────────────────────


@skip_without_git
async def test_a_repository_that_cannot_be_cloned_is_marked_failed(
    client: AsyncClient, tmp_path: Path
) -> None:
    token = await sign_up(client)
    missing = tmp_path / "does-not-exist"
    missing.mkdir()

    response = await client.post(
        f"{PREFIX}/repositories", headers=bearer(token), json={"repository": str(missing)}
    )
    repository_id = response.json()["id"]

    detail = (
        await client.get(f"{PREFIX}/repositories/{repository_id}", headers=bearer(token))
    ).json()

    assert detail["status"] == "failed"
    assert detail["error_message"]


async def test_a_non_github_url_is_rejected_before_any_clone(
    client: AsyncClient,
) -> None:
    token = await sign_up(client)

    response = await client.post(
        f"{PREFIX}/repositories",
        headers=bearer(token),
        json={"repository": "http://169.254.169.254/latest/meta-data/"},
    )

    assert response.status_code == 422


@skip_without_git
async def test_repositories_are_owner_scoped(client: AsyncClient, sample_repository: Path) -> None:
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")

    response = await client.post(
        f"{PREFIX}/repositories",
        headers=bearer(ada),
        json={"repository": str(sample_repository)},
    )
    repository_id = response.json()["id"]

    assert (await client.get(f"{PREFIX}/repositories", headers=bearer(grace))).json() == []
    assert (
        await client.get(f"{PREFIX}/repositories/{repository_id}", headers=bearer(grace))
    ).status_code == 404


async def test_importing_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(f"{PREFIX}/repositories", json={"repository": "tiangolo/fastapi"})
    assert response.status_code == 401
