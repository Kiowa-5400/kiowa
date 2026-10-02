"""Operational commands.

    python -m app.cli bootstrap-admin       # first deployment: create the initial administrator (idempotent)
    python -m app.cli create-board-user     # interactive: add a board login from the shell

Normal board administration (invites, roles, deactivation) happens in the
board app; these exist for first deployment and emergency recovery.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.permissions import ROLE_LABELS
from app.core.security import validate_new_password
from app.core.timeutil import club_today, now_utc
from app.db.session import get_sessionmaker
from app.models import BoardUser, Person
from app.services import auth as auth_service


def _ensure_board_user(email: str, first: str, last: str, role: str, password: str | None) -> str:
    with get_sessionmaker()() as db:
        person = auth_service.find_person_by_email(db, email)
        if person is None:
            person = Person(first_name=first, last_name=last, email=email.lower().strip(), membership_status="member",
                            member_since=club_today(), on_board=True)
            db.add(person)
            db.flush()
        if password:
            if problem := validate_new_password(password):
                raise SystemExit(problem)
            auth_service.set_password(db, person, password)
            person.email_verified_at = person.email_verified_at or now_utc()
        board_user = person.board_user
        if board_user is None:
            db.add(BoardUser(person_id=person.id, role=role))
        else:
            board_user.role, board_user.is_active, board_user.deactivated_at = role, True, None
        person.on_board = True
        db.commit()
        if not password:
            from app.api.auth import _link

            token = auth_service.issue_token(db, person, "board_invite")
            db.commit()
            return f"No password given. Set one within 7 days at: {_link('board', '/accept-invite', token)}"
        return f"{person.email} can now sign in to the board app as {ROLE_LABELS[role]}."


def bootstrap_admin() -> int:
    settings = get_settings()
    if not settings.bootstrap_admin_email:
        print("BOOTSTRAP_ADMIN_EMAIL is not set; nothing to do.")
        return 0
    with get_sessionmaker()() as db:
        existing = db.scalar(select(BoardUser).where(BoardUser.is_active.is_(True), BoardUser.role.in_(("tech_admin", "president"))))
        if existing is not None:
            print("An active administrator already exists; bootstrap skipped.")
            return 0
    name = (settings.bootstrap_admin_name or "Club Administrator").split(" ", 1)
    message = _ensure_board_user(settings.bootstrap_admin_email, name[0], name[1] if len(name) > 1 else "", "tech_admin",
                                 settings.bootstrap_admin_password or None)
    print(message)
    print("Remove BOOTSTRAP_ADMIN_PASSWORD from the environment now that the account exists.")
    return 0


def create_board_user(args: argparse.Namespace) -> int:
    password = getpass.getpass("Password (leave blank to email an invite link instead): ") or None
    print(_ensure_board_user(args.email, args.first_name, args.last_name, args.role, password))
    return 0


def main(argv: list[str]) -> int:
    configure_logging(get_settings().log_level)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap-admin")
    create = sub.add_parser("create-board-user")
    create.add_argument("--email", required=True)
    create.add_argument("--first-name", required=True)
    create.add_argument("--last-name", required=True)
    create.add_argument("--role", choices=list(ROLE_LABELS), default="board_member")
    args = parser.parse_args(argv[1:])
    if args.command == "bootstrap-admin":
        return bootstrap_admin()
    return create_board_user(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
