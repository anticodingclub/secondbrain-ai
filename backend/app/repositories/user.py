"""User persistence."""

from __future__ import annotations

from app.models.user import User
from app.repositories.base import SQLAlchemyRepository


class UserRepository(SQLAlchemyRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        """Look up by email, normalised the same way registration stores it."""
        return await self.find_one_by(email=normalize_email(email))

    async def email_exists(self, email: str) -> bool:
        return await self.get_by_email(email) is not None


def normalize_email(email: str) -> str:
    """Lowercase and trim.

    Applied on both write and read so `Ada@Example.com` and `ada@example.com`
    cannot become two accounts — the local part is technically case-sensitive
    per RFC 5321, but no real provider treats it that way and users assume they
    are the same address.
    """
    return email.strip().lower()
