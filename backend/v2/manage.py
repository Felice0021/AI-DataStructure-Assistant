"""Explicit local-only administration; no password CLI option or HTTP endpoint."""
import argparse
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from backend.v2.core.config import Settings
from backend.v2.core.errors import AuthError
from backend.v2.db.session import build_engine
from backend.v2.schemas.auth import Registration
from backend.v2.services.auth_service import create_user


def create_admin(email: str, password: str, settings: Settings):
    data = Registration(email=email, password=password)
    engine = build_engine(settings)
    try:
        with Session(engine) as session:
            return create_user(session, data, role="admin").id
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="V2 local administration")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        raise SystemExit("Run administrator initialization in an interactive local terminal")
    password = getpass.getpass("New administrator password: ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    try:
        create_admin(args.email, password, Settings())
    except (ValidationError, AuthError):
        raise SystemExit("Invalid credentials or email already exists; no account promoted") from None
    except SQLAlchemyError:
        raise SystemExit("Database unavailable; check connectivity and migration state") from None
    print("Administrator created; sign in through the normal login endpoint.")


if __name__ == "__main__":
    main()
