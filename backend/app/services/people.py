"""Contact database: groups, search and shared person helpers.

Groups are not mutually exclusive: a board member is also an active member,
and shooting committee members are active members too.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, Select, false, func, or_, select
from sqlalchemy.orm import Session

from app.models import BoardUser, Person

GROUPS: dict[str, str] = {
    "active_members": "Active members",
    "board": "Board",
    "shooting_committee": "Shooting committee",
    "waiting_list": "Waiting list",
    "non_members": "Non-members",
    "former": "Former / expired / terminated",
}


def group_condition(group: str) -> ColumnElement[bool]:
    if group == "active_members":
        return Person.membership_status == "member"
    if group == "board":
        has_board_login = select(BoardUser.id).where(BoardUser.person_id == Person.id, BoardUser.is_active.is_(True)).exists()
        return or_(Person.on_board.is_(True), has_board_login)
    if group == "shooting_committee":
        return Person.on_shooting_committee.is_(True)
    if group == "waiting_list":
        return Person.membership_status == "waiting_list"
    if group == "non_members":
        return Person.membership_status == "non_member"
    if group == "former":
        return Person.membership_status.in_(("expired", "terminated"))
    raise ValueError(f"Unknown group: {group}")


def validate_groups(groups: list[str]) -> list[str]:
    unknown = [g for g in groups if g not in GROUPS]
    if unknown:
        raise ValueError(f"Unknown group(s): {', '.join(unknown)}")
    return groups


def people_query(*, groups: list[str] | None = None, person_ids: list[int] | None = None) -> Select[tuple[Person]]:
    conditions: list[ColumnElement[bool]] = []
    if groups:
        conditions.append(or_(*(group_condition(g) for g in validate_groups(groups))))
    if person_ids:
        conditions.append(Person.id.in_(person_ids))
    where = or_(*conditions) if conditions else false()
    return select(Person).where(where).order_by(Person.last_name, Person.first_name)


def resolve_recipients(db: Session, *, groups: list[str], person_ids: list[int]) -> list[Person]:
    return list(db.scalars(people_query(groups=groups, person_ids=person_ids)).all())


def groups_for(person: Person) -> list[str]:
    result: list[str] = []
    if person.membership_status == "member":
        result.append("active_members")
    if person.on_board or (person.board_user and person.board_user.is_active):
        result.append("board")
    if person.on_shooting_committee:
        result.append("shooting_committee")
    if person.membership_status == "waiting_list":
        result.append("waiting_list")
    if person.membership_status == "non_member":
        result.append("non_members")
    if person.membership_status in ("expired", "terminated"):
        result.append("former")
    return result


def search_conditions(q: str | None, groups: list[str] | None, status: str | None) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if q:
        like = f"%{q.strip().lower()}%"
        conditions.append(
            or_(
                func.lower(Person.first_name + " " + Person.last_name).like(like),
                func.lower(Person.email).like(like),
                func.coalesce(Person.phone, "").like(f"%{q.strip()}%"),
                func.coalesce(Person.nra_number, "").like(f"%{q.strip()}%"),
            )
        )
    if groups:
        conditions.append(or_(*(group_condition(g) for g in validate_groups(groups))))
    if status:
        conditions.append(Person.membership_status == status)
    return conditions


def active_board_people(db: Session) -> list[Person]:
    return list(
        db.scalars(
            select(Person).join(BoardUser, BoardUser.person_id == Person.id).where(BoardUser.is_active.is_(True))
        ).all()
    )


def format_address(person: Person) -> str:
    line = ", ".join(p for p in [person.address_line1, person.address_line2] if p)
    locality = " ".join(p for p in [f"{person.city}," if person.city else None, person.state, person.zip_code] if p)
    return ", ".join(p for p in [line, locality] if p)

