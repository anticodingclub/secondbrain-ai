"""Create or update a local development account.

**Development tool. Not importable by the application, and not for production.**

Two things this does that the HTTP API deliberately will not:

1. It sets a password without enforcing ``MIN_PASSWORD_LENGTH``. That rule is a
   *registration policy*, checked at the API boundary; verification imposes no
   minimum, so a short password set here still signs in normally. The policy
   itself is untouched, which is the point — a convenience for one local
   account should not weaken the product for everyone who registers.

2. It rewrites an existing account in place rather than making a new one, so
   documents already uploaded stay attached to the same owner id.

Changing the password revokes every refresh token for that user, matching what
a real password change must do: sessions opened with the old credential stop
working.

    python scripts/dev_account.py --email you@example.com --name "Your Name" \
        --password your-dev-password

The address still has to satisfy the app's own validation, which rejects bare
hostnames (``you@localhost``) and special-use domains (``.test``, ``.local``,
``.invalid``). ``example.com`` is IANA-reserved for documentation, so it can
never be a real mailbox while remaining a valid one.

Pass ``--replaces old@example.com`` to rename an existing account in place,
keeping the documents already attached to it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

# Runnable as a plain script from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, update

from app.core.config import get_settings

# Imported privately on purpose: reusing the application's configured hasher
# guarantees the cost parameters cannot drift from the ones login verifies
# against. Exposing an unchecked hash helper in app code would invite misuse.
from app.core.security import _hasher
from app.db.session import create_engine, create_session_factory
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.user import normalize_email


async def upsert_account(
    *, email: str, display_name: str, password: str, replaces: str | None
) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    email = normalize_email(email)
    lookup = normalize_email(replaces) if replaces else email

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == lookup))
        ).scalar_one_or_none()

        if user is None and replaces:
            # Falling back to the target email means re-running the script is
            # idempotent rather than failing once the rename has happened.
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()

        action = "updated"
        if user is None:
            action = "created"
            user = User(email=email, display_name=display_name, hashed_password="")
            session.add(user)

        user.email = email
        user.display_name = display_name
        user.hashed_password = _hasher.hash(password)
        user.is_active = True

        await session.flush()

        revoked = await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.is_active.is_(True))
            .values(is_active=False, revoked_at=datetime.now(UTC))
        )
        await session.commit()

        print(f"Account {action}.")
        print(f"  id            {user.id}")
        print(f"  email         {user.email}")
        print(f"  display name  {user.display_name}")
        print(f"  password      {'*' * len(password)} ({len(password)} characters)")
        print(f"  sessions      {revoked.rowcount or 0} revoked — sign in again")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Sign-in address.")
    parser.add_argument("--name", required=True, help="Display name.")
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--replaces",
        default=None,
        help="Existing address to rename, keeping its documents.",
    )
    args = parser.parse_args()

    asyncio.run(
        upsert_account(
            email=args.email,
            display_name=args.name,
            password=args.password,
            replaces=args.replaces,
        )
    )


if __name__ == "__main__":
    main()
