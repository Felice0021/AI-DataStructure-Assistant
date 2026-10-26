from datetime import timedelta
import math

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.v2.core.config import Settings
from backend.v2.core.errors import AuthError
from backend.v2.core.security import PASSWORD_HASHER, new_token, token_digest, verify_password
from backend.v2.models import AuthSession, LoginLimit, User
from backend.v2.schemas.auth import Registration


def create_user(session: Session, data: Registration, *, role: str = "student") -> User:
    user = User(email=str(data.email), password_hash=PASSWORD_HASHER.hash(data.password.get_secret_value()), role=role)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if getattr(getattr(error.orig, "diag", None), "constraint_name", None) == "uq_users_email_ci":
            raise AuthError(409, "email_exists", "Email already registered") from None
        raise
    return user


def lock_login_limits(session: Session, email: str, ip: str, settings: Settings):
    limits = {
        token_digest("email:" + email): settings.login_max_failures,
        token_digest("ip:" + ip): settings.login_ip_max_failures,
    }
    buckets = []
    # Fixed order avoids deadlocks when different processes share a bucket.
    for key in sorted(limits):
        session.execute(insert(LoginLimit).values(key=key).on_conflict_do_nothing(index_elements=["key"]))
        buckets.append(session.scalar(select(LoginLimit).where(LoginLimit.key == key).with_for_update()))
    now = session.scalar(select(func.clock_timestamp()))
    retry_after = 0
    for bucket in buckets:
        end = bucket.window_started_at + timedelta(seconds=settings.login_window_seconds)
        if end <= now:
            bucket.window_started_at, bucket.failures = now, 0
        elif bucket.failures >= limits[bucket.key]:
            retry_after = max(retry_after, math.ceil((end - now).total_seconds()))
    if retry_after:
        session.commit()
        raise AuthError(429, "login_rate_limited", "Too many login attempts", {"Retry-After": str(retry_after)})
    return buckets, now


def login(session: Session, email: str, password: str, ip: str, settings: Settings):
    buckets, now = lock_login_limits(session, email, ip, settings)
    user = session.scalar(select(User).where(func.lower(User.email) == email))
    valid, replacement = verify_password(password, user.password_hash if user else None)
    if not user or not valid or not user.is_active:
        for bucket in buckets:
            bucket.failures += 1
        session.commit()  # Persist failures across requests, workers and restarts.
        raise AuthError(401, "invalid_credentials", "Invalid email or password")
    if replacement:
        user.password_hash = replacement
    for bucket in buckets:
        if bucket.key == token_digest("email:" + email):
            bucket.failures = 0
    raw = new_token()
    expires_at = now + timedelta(seconds=settings.session_ttl_seconds)
    session.add(AuthSession(user_id=user.id, token_hash=token_digest(raw), expires_at=expires_at))
    session.commit()
    return user, raw, expires_at


def logout(session: Session, raw: str) -> None:
    record = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(raw)).with_for_update())
    if record is not None and record.revoked_at is None:
        record.revoked_at = session.scalar(select(func.clock_timestamp()))
    session.commit()
