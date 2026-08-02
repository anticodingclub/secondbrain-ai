"""Refresh-cookie mechanics.

Kept in one module because both the auth routes (success paths) and the error
handler (failure paths) must agree exactly on the name, path and flags — a
`delete_cookie` whose path differs from the `set_cookie` is a no-op, and the
resulting bug is invisible until a user is stuck in a refresh loop.
"""

from __future__ import annotations

from datetime import datetime

from starlette.responses import Response

from app.core.config import Settings

COOKIE_NAME = "secondbrain_refresh"

#: Scoped to the auth endpoints so this long-lived credential is not attached
#: to every ordinary API request.
COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(
    response: Response, *, token: str, expires_at: datetime, settings: Settings
) -> None:
    """Attach the refresh token as a hardened cookie.

    httpOnly keeps it out of reach of JavaScript, so an XSS on the page cannot
    exfiltrate a 14-day credential. SameSite=lax stops a third-party site from
    silently triggering a refresh. See `Settings.cookie_secure` for why
    `secure` is not unconditionally on.
    """
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
        expires=expires_at,
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path=COOKIE_PATH)
