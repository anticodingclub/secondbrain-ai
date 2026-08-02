"""Full authentication flows through the real ASGI app."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.api.cookies import COOKIE_NAME as REFRESH_COOKIE_NAME

pytestmark = pytest.mark.integration

PREFIX = "/api/v1"

CREDENTIALS = {
    "email": "ada@example.com",
    "password": "correct-horse-battery",
    "display_name": "Ada Lovelace",
}


async def register(client: AsyncClient, **overrides: str):
    return await client.post(f"{PREFIX}/auth/register", json={**CREDENTIALS, **overrides})


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Registration ─────────────────────────────────────────────────────────────


async def test_register_returns_tokens_and_the_new_user(client: AsyncClient) -> None:
    response = await register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["display_name"] == "Ada Lovelace"


async def test_register_never_returns_the_password_or_its_hash(client: AsyncClient) -> None:
    body = (await register(client)).text
    assert CREDENTIALS["password"] not in body
    assert "argon2" not in body
    assert "hashed_password" not in body


async def test_refresh_token_is_only_ever_an_httponly_cookie(client: AsyncClient) -> None:
    response = await register(client)

    assert "refresh_token" not in response.json()
    cookie = response.cookies.get(REFRESH_COOKIE_NAME)
    assert cookie
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


async def test_email_is_normalised_to_lowercase(client: AsyncClient) -> None:
    response = await register(client, email="Ada@Example.COM")
    assert response.json()["user"]["email"] == "ada@example.com"


async def test_duplicate_email_is_rejected_case_insensitively(client: AsyncClient) -> None:
    await register(client)
    response = await register(client, email="ADA@example.com")

    assert response.status_code == 409
    assert response.json()["error"] == "conflict"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("email", "not-an-email"),
        ("password", "short"),
        ("display_name", "   "),
    ],
)
async def test_invalid_registration_input_is_rejected(
    client: AsyncClient, field: str, value: str
) -> None:
    response = await register(client, **{field: value})
    assert response.status_code == 422
    assert response.json()["error"] == "validation_error"


# ── Login ────────────────────────────────────────────────────────────────────


async def test_login_with_correct_credentials(client: AsyncClient) -> None:
    await register(client)
    response = await client.post(
        f"{PREFIX}/auth/login",
        json={"email": CREDENTIALS["email"], "password": CREDENTIALS["password"]},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("ada@example.com", "wrong-password-entirely"),
        ("nobody@example.com", "correct-horse-battery"),
    ],
    ids=["wrong password", "unknown user"],
)
async def test_login_failures_are_indistinguishable(
    client: AsyncClient, email: str, password: str
) -> None:
    """Both cases must return the same status and wording, or the endpoint
    becomes an account-enumeration oracle."""
    await register(client)
    response = await client.post(
        f"{PREFIX}/auth/login", json={"email": email, "password": password}
    )

    assert response.status_code == 401
    assert response.json()["message"] == "Incorrect email or password."


# ── Protected routes ─────────────────────────────────────────────────────────


async def test_me_returns_the_signed_in_user(client: AsyncClient) -> None:
    token = (await register(client)).json()["access_token"]

    response = await client.get(f"{PREFIX}/auth/me", headers=auth_header(token))

    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-real-token"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
    ],
    ids=["missing", "garbage", "empty", "wrong scheme"],
)
async def test_protected_route_rejects_bad_credentials(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get(f"{PREFIX}/auth/me", headers=headers)
    assert response.status_code == 401


async def test_refresh_token_cannot_be_used_as_an_access_token(client: AsyncClient) -> None:
    response = await register(client)
    refresh_cookie = response.cookies.get(REFRESH_COOKIE_NAME)

    result = await client.get(f"{PREFIX}/auth/me", headers=auth_header(refresh_cookie or ""))

    assert result.status_code == 401


# ── Rotation and replay ──────────────────────────────────────────────────────


async def test_refresh_issues_a_new_token_pair(client: AsyncClient) -> None:
    original = await register(client)
    original_cookie = original.cookies.get(REFRESH_COOKIE_NAME)

    response = await client.post(f"{PREFIX}/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"]
    # Rotation: the cookie must actually change, or nothing was rotated.
    assert response.cookies.get(REFRESH_COOKIE_NAME) != original_cookie


async def test_replaying_a_consumed_refresh_token_kills_the_whole_session(
    client: AsyncClient,
) -> None:
    """The core defence. A stolen token is only useful until the real client
    refreshes; after that, using it burns the entire family."""
    await register(client)
    stolen = client.cookies.get(REFRESH_COOKIE_NAME)

    # The legitimate client refreshes, consuming `stolen`.
    assert (await client.post(f"{PREFIX}/auth/refresh")).status_code == 200
    rotated = client.cookies.get(REFRESH_COOKIE_NAME)
    assert rotated != stolen

    # The attacker replays the consumed token.
    client.cookies.set(REFRESH_COOKIE_NAME, stolen or "", path="/api/v1/auth")
    replay = await client.post(f"{PREFIX}/auth/refresh")
    assert replay.status_code == 401

    # ...which must also invalidate the legitimate client's rotated token.
    client.cookies.set(REFRESH_COOKIE_NAME, rotated or "", path="/api/v1/auth")
    assert (await client.post(f"{PREFIX}/auth/refresh")).status_code == 401


async def test_refresh_without_a_cookie_is_rejected(client: AsyncClient) -> None:
    response = await client.post(f"{PREFIX}/auth/refresh")
    assert response.status_code == 401


async def test_failed_refresh_clears_the_dead_cookie(client: AsyncClient) -> None:
    client.cookies.set(REFRESH_COOKIE_NAME, "garbage-token", path="/api/v1/auth")

    response = await client.post(f"{PREFIX}/auth/refresh")

    assert response.status_code == 401
    assert 'secondbrain_refresh=""' in response.headers.get("set-cookie", "")


# ── Logout ───────────────────────────────────────────────────────────────────


async def test_logout_invalidates_the_session(client: AsyncClient) -> None:
    await register(client)
    refresh_cookie = client.cookies.get(REFRESH_COOKIE_NAME)

    assert (await client.post(f"{PREFIX}/auth/logout")).status_code == 204

    client.cookies.set(REFRESH_COOKIE_NAME, refresh_cookie or "", path="/api/v1/auth")
    assert (await client.post(f"{PREFIX}/auth/refresh")).status_code == 401


async def test_logout_without_a_session_is_a_no_op(client: AsyncClient) -> None:
    """Logging out must never fail, or the client cannot clear its own state."""
    assert (await client.post(f"{PREFIX}/auth/logout")).status_code == 204


async def test_logout_all_revokes_every_session(client: AsyncClient) -> None:
    token = (await register(client)).json()["access_token"]
    session_cookie = client.cookies.get(REFRESH_COOKIE_NAME)

    response = await client.post(f"{PREFIX}/auth/logout-all", headers=auth_header(token))
    assert response.status_code == 204

    client.cookies.set(REFRESH_COOKIE_NAME, session_cookie or "", path="/api/v1/auth")
    assert (await client.post(f"{PREFIX}/auth/refresh")).status_code == 401


# ── Tenant isolation ─────────────────────────────────────────────────────────


async def test_two_users_resolve_to_distinct_identities(client: AsyncClient) -> None:
    """The boundary every later phase filters on."""
    ada = (await register(client)).json()
    grace = (await register(client, email="grace@example.com", display_name="Grace Hopper")).json()

    assert ada["user"]["id"] != grace["user"]["id"]

    seen_by_ada = await client.get(f"{PREFIX}/auth/me", headers=auth_header(ada["access_token"]))
    seen_by_grace = await client.get(
        f"{PREFIX}/auth/me", headers=auth_header(grace["access_token"])
    )

    assert seen_by_ada.json()["id"] == ada["user"]["id"]
    assert seen_by_grace.json()["id"] == grace["user"]["id"]
