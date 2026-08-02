"""Authentication endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Request, Response, status

from app.api.cookies import COOKIE_NAME, clear_refresh_cookie, set_refresh_cookie
from app.api.dependencies import AuthServiceDep, CurrentUser, SettingsDep
from app.core.config import Settings
from app.core.exceptions import InvalidSessionError
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.auth import ClientContext, IssuedTokens

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_context(request: Request) -> ClientContext:
    return ClientContext(
        user_agent=request.headers.get("user-agent"),
        # Behind a proxy this needs X-Forwarded-For plus a trusted-hop count;
        # it is recorded for audit only and never used for authorisation.
        ip_address=request.client.host if request.client else None,
    )


def _issue(response: Response, tokens: IssuedTokens, settings: Settings) -> None:
    set_refresh_cookie(
        response,
        token=tokens.refresh_token,
        expires_at=tokens.refresh_expires_at,
        settings=settings,
    )


def _token_response(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        expires_in=tokens.access_expires_in,
        user=UserResponse.model_validate(tokens.user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and sign in",
)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
) -> TokenResponse:
    tokens = await auth_service.register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        context=_client_context(request),
    )
    _issue(response, tokens, settings)
    return _token_response(tokens)


@router.post("/login", response_model=TokenResponse, summary="Sign in")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
) -> TokenResponse:
    tokens = await auth_service.authenticate(
        email=payload.email,
        password=payload.password,
        context=_client_context(request),
    )
    _issue(response, tokens, settings)
    return _token_response(tokens)


@router.post("/refresh", response_model=TokenResponse, summary="Rotate the session")
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthServiceDep,
    settings: SettingsDep,
    secondbrain_refresh: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> TokenResponse:
    if not secondbrain_refresh:
        raise InvalidSessionError("No active session.")

    # Failures raise InvalidSessionError, and the error handler is what clears
    # the dead cookie — mutating `response` here would be lost on the raise.
    tokens = await auth_service.refresh(
        refresh_token=secondbrain_refresh, context=_client_context(request)
    )
    _issue(response, tokens, settings)
    return _token_response(tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out")
async def logout(
    response: Response,
    auth_service: AuthServiceDep,
    secondbrain_refresh: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> None:
    await auth_service.logout(refresh_token=secondbrain_refresh)
    clear_refresh_cookie(response)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out of every device",
)
async def logout_all(
    response: Response, current_user: CurrentUser, auth_service: AuthServiceDep
) -> None:
    await auth_service.logout_everywhere(user_id=current_user.id)
    clear_refresh_cookie(response)


@router.get("/me", response_model=UserResponse, summary="The signed-in user")
async def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)
