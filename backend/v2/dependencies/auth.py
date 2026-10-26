import hmac
import re
from ipaddress import ip_address
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.v2.core.errors import AuthError, unauthorized
from backend.v2.core.security import TOKEN_PATTERN, csrf_token, token_digest
from backend.v2.dependencies.database import get_session
from backend.v2.models import AuthSession, User


def check_transport(request: Request) -> None:
    settings = request.app.state.settings
    if settings.cookie_secure:
        if request.url.scheme != "https":
            raise AuthError(403, "https_required", "HTTPS is required")
    else:
        try:
            local_client = request.client is not None and ip_address(request.client.host).is_loopback
        except ValueError:
            local_client = False
        if request.url.hostname not in {"127.0.0.1", "localhost", "::1"} or not local_client:
            raise AuthError(403, "loopback_required", "Loopback development access required")
    origins = request.headers.getlist("origin")
    if origins and (len(origins) != 1 or origins[0] not in settings.allowed_origins):
        raise AuthError(403, "origin_rejected", "Origin not allowed")


def require_csrf(request: Request) -> None:
    check_transport(request)
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    settings = request.app.state.settings
    if request.headers.get("origin") not in settings.allowed_origins:
        raise AuthError(403, "origin_rejected", "Origin not allowed")
    secret = request.cookies.get(settings.session_cookie) or request.cookies.get(settings.csrf_cookie)
    provided = request.headers.get("x-csrf-token", "")
    if (not secret or not TOKEN_PATTERN.fullmatch(secret) or not re.fullmatch(r"[0-9a-f]{64}", provided)
        or not hmac.compare_digest(provided, csrf_token(secret))):
        raise AuthError(403, "csrf_rejected", "CSRF verification failed")


def get_current_user(
    request: Request, session: Annotated[Session, Depends(get_session)],
) -> User:
    require_csrf(request)
    raw = request.cookies.get(request.app.state.settings.session_cookie, "")
    if not TOKEN_PATTERN.fullmatch(raw):
        raise unauthorized()
    user = session.scalar(
        select(User).join(AuthSession, AuthSession.user_id == User.id).where(
            AuthSession.token_hash == token_digest(raw),
            AuthSession.revoked_at.is_(None), AuthSession.expires_at > func.now(),
            User.is_active.is_(True),
        )
    )
    if user is None:
        raise unauthorized()
    return user


def require_active_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    # get_current_user already enforces active status on every request.
    return user


def require_role(*roles: str):
    if not roles or not set(roles) <= {"student", "admin"}:
        raise ValueError("Specify supported roles explicitly")

    def dependency(user: Annotated[User, Depends(require_active_user)]) -> User:
        if user.role not in roles:
            raise AuthError(403, "forbidden", "Insufficient permissions")
        return user

    return dependency
