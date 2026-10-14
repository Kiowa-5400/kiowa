"""Spotting two records for one person, and the board combining them or saying they're different people."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.core.security import hash_password
from app.core.timeutil import now_utc
from app.models import Application, BoardUser, Person
from tests.helpers import FULL_PROFILE, PASSWORD, board, member, sign_in


def _roster_and_signup(db) -> tuple[Person, Person]:
    """A roster member the club had no email for, and the second record they made by signing up."""
    roster = Person(first_name="Joe", last_name="Felke", phone="(620) 617-1876", membership_status="member",
                    renewal_date=date(2026, 9, 10), member_number=15, nra_life_member=True, notes="Officer")
    signup = Person(first_name="Joseph", last_name="Felke", email="joseph@example.com", phone="620-617-1876",
                    membership_status="non_member", city="Great Bend", password_hash=hash_password(PASSWORD),
                    email_verified_at=now_utc())
    db.add_all([roster, signup])
    db.flush()
    db.add(Application(person_id=signup.id, application_type="waiting_list", status="draft"))
    db.commit()
    return roster, signup


def test_board_combines_roster_member_with_their_new_account(api, new_api, db):
    board(api, db)
    roster, signup = _roster_and_signup(db)
    signup_id = signup.id

    pairs = api.get("/api/board/people/duplicates").json()
    assert [(p["keep"]["id"], p["other"]["id"]) for p in pairs] == [(roster.id, signup.id)]
    assert [m["id"] for m in api.get(f"/api/board/people/{signup.id}/matches").json()] == [roster.id]

    # The roster record is kept whichever page the board starts from.
    preview = api.get(f"/api/board/people/{signup.id}/combine/{roster.id}").json()
    assert preview["problem"] is None and preview["keep"]["id"] == roster.id
    assert preview["combined"]["email"] == "joseph@example.com" and preview["combined"]["membership_status"] == "member"
    assert any("waiting-list application will be cancelled" in n for n in preview["notes"])

    response = api.post(f"/api/board/people/{signup.id}/combine/{roster.id}")
    assert response.status_code == 200, response.text
    assert response.json() == {"person_id": roster.id}

    db.expire_all()
    assert db.get(Person, signup_id) is None
    kept = db.get(Person, roster.id)
    assert (kept.first_name, kept.email, kept.membership_status, kept.city) == ("Joe", "joseph@example.com", "member", "Great Bend")
    assert kept.member_number == 15 and kept.nra_life_member and kept.renewal_date == date(2026, 9, 10)
    application = db.scalar(select(Application).where(Application.person_id == roster.id))
    assert application.status == "withdrawn"
    assert api.get("/api/board/people/duplicates").json() == []

    # They sign in with their own email and password and are a member now.
    joseph = new_api()
    sign_in(joseph, "joseph@example.com")
    assert joseph.get("/api/me").json()["membership_status"] == "member"


def test_different_people_sharing_a_phone(api, new_api, db):
    board(api, db)
    spouse = Person(first_name="Sam", last_name="Shooter", phone="6205550100", membership_status="member")
    db.add(spouse)
    db.commit()
    pat_api = new_api()
    member(pat_api, "pat@example.com", **FULL_PROFILE)
    refused = pat_api.post("/api/applications", json={"application_type": "waiting_list"})
    assert refused.status_code == 409 and "contact the board" in refused.json()["detail"]

    pat = db.scalar(select(Person).where(Person.email == "pat@example.com"))
    assert api.post(f"/api/board/people/{pat.id}/not-duplicate/{spouse.id}").status_code == 200
    assert api.get("/api/board/people/duplicates").json() == []
    assert pat_api.post("/api/applications", json={"application_type": "waiting_list"}).status_code == 201


def test_cannot_combine_two_board_sign_ins(api, db):
    board(api, db)
    roster, signup = _roster_and_signup(db)
    db.add_all([BoardUser(person_id=roster.id, role="board_member"), BoardUser(person_id=signup.id, role="board_member")])
    db.commit()
    assert api.get(f"/api/board/people/{roster.id}/combine/{signup.id}").json()["problem"]
    response = api.post(f"/api/board/people/{roster.id}/combine/{signup.id}")
    assert response.status_code == 409 and "board sign-in" in response.json()["detail"]
    db.expire_all()
    assert db.get(Person, signup.id) is not None



def test_preview_only_warns_about_details_that_really_differ(api, db):
    board(api, db)
    roster, signup = _roster_and_signup(db)  # same phone number, written two ways
    signup.address_line1 = "9 Other Rd"
    roster.address_line1 = "14 SE 35 Ave."
    db.commit()
    notes = api.get(f"/api/board/people/{roster.id}/combine/{signup.id}").json()["notes"]
    assert not any("phone number" in n for n in notes)
    assert any("The address 9 Other Rd won't be kept" in n for n in notes)
