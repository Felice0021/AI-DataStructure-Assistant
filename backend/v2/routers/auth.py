from typing import Annotated
from datetime import timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from backend.v2.core.security import TOKEN_PATTERN, csrf_token, new_token
from backend.v2.dependencies.auth import check_transport, get_current_user, require_csrf
from backend.v2.dependencies.database import get_session
from backend.v2.models import User
from backend.v2.schemas.auth import Credentials, CsrfResponse, ErrorResponse, Registration, UserEnvelope, UserResponse
from backend.v2.services import auth_service

router = APIRouter(
    prefix="/api/v2/auth", tags=["auth"], dependencies=[Depends(check_transport)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 409, 422, 429, 500, 503)},
)


def set_cookie(response: Response, settings, name, value, max_age, expires=None):
    response.set_cookie(
        key=name, value=value, max_age=max_age,
        expires=expires.astimezone(timezone.utc) if expires is not None else None,
        path="/", secure=settings.cookie_secure, httponly=True, samesite="lax",
    )


def clear_cookie(response: Response, settings, name):
    response.delete_cookie(name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")


@router.get("/csrf", response_model=CsrfResponse)
def get_csrf(request: Request, response: Response):
    settings = request.app.state.settings
    secret = request.cookies.get(settings.session_cookie) or request.cookies.get(settings.csrf_cookie)
    if not secret or not TOKEN_PATTERN.fullmatch(secret):
        secret = new_token()
        set_cookie(response, settings, settings.csrf_cookie, secret, 1800)
    return CsrfResponse(csrf_token=csrf_token(secret))


@router.post("/register", status_code=201, response_model=UserEnvelope, dependencies=[Depends(require_csrf)])
def register(data: Registration, session: Annotated[Session, Depends(get_session)]):
    user = auth_service.create_user(session, data)
    return UserEnvelope(user=UserResponse.model_validate(user))


@router.post("/login", response_model=UserEnvelope, dependencies=[Depends(require_csrf)])
def login(data: Credentials, request: Request, response: Response, session: Annotated[Session, Depends(get_session)]):
    settings = request.app.state.settings
    # Ignore client-supplied forwarding headers. Configure trusted proxies explicitly at deployment.
    ip = request.client.host if request.client else "unknown"
    user, raw, expires_at = auth_service.login(session, str(data.email), data.password.get_secret_value(), ip, settings)
    set_cookie(response, settings, settings.session_cookie, raw, settings.session_ttl_seconds, expires_at)
    clear_cookie(response, settings, settings.csrf_cookie)
    return UserEnvelope(user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserEnvelope)
def me(user: Annotated[User, Depends(get_current_user)]):
    return UserEnvelope(user=UserResponse.model_validate(user))


@router.post("/logout", status_code=204, dependencies=[Depends(require_csrf)])
def logout(request: Request, session: Annotated[Session, Depends(get_session)]):
    settings = request.app.state.settings
    raw = request.cookies.get(settings.session_cookie, "")
    if TOKEN_PATTERN.fullmatch(raw):
        auth_service.logout(session, raw)
    response = Response(status_code=204)
    clear_cookie(response, settings, settings.session_cookie)
    clear_cookie(response, settings, settings.csrf_cookie)
    return response
