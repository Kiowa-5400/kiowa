"""CMS, site images, public documents, calendar with recurrence, matches with photos."""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import select

from app.models import AuditLog, CalendarEvent
from app.services import recurrence
from app.services.html import sanitize_html
from tests.helpers import PDF, PNG, board


def test_public_site_and_pages_come_from_database(api):
    site = api.get("/api/public/site").json()
    assert site["site_title"] == "Kiowa Gun Club" and site["contact_email"] == "kiowa369@outlook.com"
    assert site["images"]["logo"] is None  # falls back to the bundled asset
    home = api.get("/api/public/pages/home").json()
    assert [s["section_key"] for s in home][:2] == ["hero", "welcome"]
    assert api.get("/api/public/pages/nonexistent").status_code == 404


def test_cms_edit_sanitizes_html_and_audits(api, new_api, db):
    board(api, db, role="board_member")
    section = api.get("/api/board/pages").json()[0]["sections"][1]
    response = api.put(f"/api/board/sections/{section['id']}", json={
        "heading": "Welcome!",
        "body_html": '<p onclick="steal()">Hi <script>alert(1)</script><a href="javascript:alert(1)">x</a>'
                     '<a href="https://kiowagunclub.org">ok</a><img src=x onerror=alert(1)></p>',
    })
    body = response.json()["body_html"]
    assert "script" not in body and "onclick" not in body and "javascript:" not in body and "onerror" not in body
    assert 'href="https://kiowagunclub.org"' in body
    public = {s["id"]: s for s in new_api().get("/api/public/pages/home").json()}
    assert public[section["id"]]["body_html"] == body
    assert db.scalar(select(AuditLog).where(AuditLog.action == "cms.section_updated"))


def test_custom_sections_hide_and_delete(api, db):
    board(api, db)
    created = api.post("/api/board/pages/about/sections", json={"heading": "Range Hours", "body_html": "<p>Dawn to dusk</p>"}).json()
    assert created["is_custom"]
    builtin = api.get("/api/board/pages").json()[1]["sections"][0]
    assert api.delete(f"/api/board/sections/{builtin['id']}").status_code == 409
    api.put(f"/api/board/sections/{builtin['id']}", json={"heading": builtin["heading"], "body_html": builtin["body_html"], "is_visible": False})
    keys = [s["section_key"] for s in api.get("/api/public/pages/about").json()]
    assert builtin["section_key"] not in keys and created["section_key"] in keys
    assert api.delete(f"/api/board/sections/{created['id']}").status_code == 200


def test_settings_permissions_and_rules_versioning(api, new_api, db):
    member_board = new_api()
    board(member_board, db, "bm@example.com", "board_member")
    payload = {"dues_amount": "160.00", "cleanup_discount_amount": "25.00", "renewal_cutoff_month": 9,
               "renewal_cutoff_day": 10, "accepting_waiting_list": True}
    assert member_board.put("/api/board/settings/membership", json=payload).status_code == 403
    board(api, db)
    assert api.put("/api/board/settings/membership", json=payload).json()["dues_amount"] == "160.00"
    assert api.get("/api/application/form").json()["dues_amount"] == "160.00"
    bad_date = api.put("/api/board/settings/membership", json={**payload, "renewal_cutoff_month": 2, "renewal_cutoff_day": 30})
    assert bad_date.status_code == 422
    # February 29 is a real date; it is honored as the 28th in years without one, whatever year it is saved in.
    leap_day = api.put("/api/board/settings/membership", json={**payload, "renewal_cutoff_month": 2, "renewal_cutoff_day": 29})
    assert leap_day.status_code == 200
    api.put("/api/board/settings/membership", json=payload)

    rules = api.put("/api/board/settings/rules", json={"range_rules": ["Rule one", "Rule two"], "agreement_clause": "I agree.", "reporting_clause": ""}).json()
    assert rules["rules_version"] == date.today().isoformat()
    again = api.put("/api/board/settings/rules", json={"range_rules": ["Rule one"], "agreement_clause": "I agree.", "reporting_clause": ""}).json()
    assert again["rules_version"] == f"{date.today().isoformat()}.2"
    assert api.get("/api/public/rules").json()["rules"] == ["Rule one"]

    site = api.put("/api/board/settings/site", json={"site_title": "Kiowa Gun Club", "site_subtitle": "Great Bend, KS",
                                                      "social_facebook": "http://insecure.example"})
    assert site.status_code == 422


def test_site_image_replace_and_reset(api, db):
    board(api, db)
    response = api.put("/api/board/images/hero", files={"file": ("hero.png", PNG, "image/png")}, data={"alt_text": "Range at dawn"})
    assert response.status_code == 200
    url = api.get("/api/public/site").json()["images"]["hero"]
    assert url and "/api/public/images/hero" in url
    assert api.get("/api/public/images/hero").content == PNG
    assert api.put("/api/board/images/hero", files={"file": ("x.pdf", PDF, "application/pdf")}).status_code == 400
    assert api.put("/api/board/images/not-a-slot", files={"file": ("hero.png", PNG, "image/png")}).status_code == 404
    api.delete("/api/board/images/hero")
    assert api.get("/api/public/site").json()["images"]["hero"] is None


def test_public_documents(api, new_api, db):
    board(api, db)
    created = api.post("/api/board/public-documents", data={"title": "2026 Rules Agreement", "category": "membership"},
                       files={"file": ("rules.pdf", PDF, "application/pdf")}).json()
    visitor = new_api()
    listed = visitor.get("/api/public/documents").json()
    assert listed[0]["title"] == "2026 Rules Agreement"
    assert visitor.get(f"/api/public/documents/{created['id']}/file").content == PDF
    api.patch(f"/api/board/public-documents/{created['id']}", json={"title": "Hidden", "is_published": False})
    assert visitor.get("/api/public/documents").json() == []
    assert visitor.get(f"/api/public/documents/{created['id']}/file").status_code == 404


def test_sanitizer_unit():
    assert sanitize_html('<p style="x">ok</p><iframe src="https://x"></iframe>') == "<p>ok</p>"
    assert 'rel="noopener noreferrer"' in sanitize_html('<a href="https://x.org">x</a>')


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def test_recurrence_rules():
    assert recurrence.nth_weekday_of_month(2026, 10, 6, 2) == date(2026, 10, 10)  # 2nd Saturday
    assert recurrence.nth_weekday_of_month(2026, 9, 2, 4) == date(2026, 9, 22)  # 4th Tuesday
    assert recurrence.nth_weekday_of_month(2026, 10, 5, 5) == date(2026, 10, 30)  # last Friday
    assert recurrence.nth_weekday_of_month(2026, 2, 0, 5) == date(2026, 2, 22)
    assert recurrence.describe_recurrence(2, 6) == "Every 2nd Saturday of the month"
    dates = recurrence.series_dates(weekday=6, nth=2, start_year=2026, start_month=11, month_count=3)
    assert dates == [date(2026, 11, 14), date(2026, 12, 12), date(2027, 1, 9)]


def test_seeded_calendar_is_public(api):
    events = api.get("/api/public/calendar?start=2026-10-01&end=2026-10-31").json()
    titles = {(e["title"], e["local_date"], e["local_time"]) for e in events}
    assert ("Defensive Pistol Shoot", "2026-10-10", "09:00") in titles
    assert ("Club Member Shooting Session", "2026-10-27", "18:00") in titles
    assert all(e["recurrence_label"] for e in events)


def test_calendar_crud_with_attachments_and_kansas_time(api, new_api, db):
    board(api, db, role="board_member")
    created = api.post("/api/board/calendar", data={
        "title": "Work Day", "event_date": "2026-11-07", "start_time": "08:30", "end_time": "12:00", "category": "event",
        "description_html": "<p>Bring gloves</p><script>x</script>", "link_url": "https://example.org/signup", "link_label": "Sign up",
    }, files={"image": ("flyer.png", PNG, "image/png"), "document": ("signup.pdf", PDF, "application/pdf")})
    assert created.status_code == 201, created.text
    event = created.json()
    assert event["local_time"] == "08:30" and event["starts_at"].startswith("2026-11-07T14:30")  # CST = UTC-6
    assert "script" not in event["description_html"]
    visitor = new_api()
    public = visitor.get(f"/api/public/calendar/{event['id']}").json()
    assert visitor.get(public["image_url"].replace("http://testserver", "")).content == PNG
    assert visitor.get(public["document_url"].replace("http://testserver", "")).content == PDF

    summer = api.post("/api/board/calendar", data={"title": "Summer", "event_date": "2026-07-04", "start_time": "08:30"}).json()
    assert summer["starts_at"].startswith("2026-07-04T13:30")  # CDT = UTC-5

    updated = api.patch(f"/api/board/calendar/{event['id']}", data={
        "title": "Spring Work Day", "event_date": "2026-11-08", "start_time": "09:00", "category": "event", "remove_image": "true",
    })
    assert updated.json()["title"] == "Spring Work Day" and updated.json()["image_url"] is None
    assert updated.json()["document_url"]
    bad = api.patch(f"/api/board/calendar/{event['id']}", data={"title": "x", "event_date": "2026-11-08", "start_time": "09:00", "link_url": "javascript:alert(1)"})
    assert bad.status_code == 422
    assert api.delete(f"/api/board/calendar/{event['id']}").status_code == 200
    assert visitor.get(f"/api/public/calendar/{event['id']}").status_code == 404


def test_recurring_series_create_edit_and_delete(api, new_api, db):
    board(api, db)
    preview = api.post("/api/board/calendar/series/preview", json={
        "title": "Carbine Match", "weekday": 0, "nth": 3, "start_time": "13:00", "category": "match",
        "start_year": 2027, "start_month": 1, "month_count": 3}).json()
    assert preview["label"] == "Every 3rd Sunday of the month"
    assert preview["dates"] == ["2027-01-17", "2027-02-21", "2027-03-21"]
    created = api.post("/api/board/calendar/series", json={
        "title": "Carbine Match", "weekday": 0, "nth": 3, "start_time": "13:00", "end_time": "16:00", "category": "match",
        "start_year": 2027, "start_month": 1, "month_count": 3}).json()
    assert created["created"] == 3
    events = [e for e in new_api().get("/api/public/calendar?start=2027-01-01&end=2027-03-31").json() if e["title"] == "Carbine Match"]
    assert len(events) == 3 and {e["series_id"] for e in events} == {created["series_id"]}
    assert events[0]["local_end_time"] == "16:00"
    # Occurrences are individually editable.
    api.patch(f"/api/board/calendar/{events[1]['id']}", data={"title": "Carbine Match (moved)", "event_date": "2027-02-28", "start_time": "13:00", "category": "match"})
    assert db.get(CalendarEvent, events[1]["id"]).title == "Carbine Match (moved)"
    api.delete(f"/api/board/calendar/series/{created['series_id']}?scope=all")
    assert not [e for e in api.get("/api/board/calendar?start=2027-01-01&end=2027-03-31").json() if e["series_id"] == created["series_id"]]


def test_calendar_requires_permission(new_api):
    assert new_api().post("/api/board/calendar", data={"title": "x", "event_date": "2026-11-07"}).status_code == 401


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def test_matches_grouped_by_discipline_with_results_and_photos(api, new_api, db):
    board(api, db, role="board_member")
    created = api.post("/api/board/matches", json={"discipline": "Carbine", "event_date": "2026-11-21", "start_time": "10:00",
                                                     "notes": "Bring 200 rounds"}).json()
    assert api.post("/api/board/matches", json={"event_date": "2026-11-21", "results_url": "ftp://bad"}).status_code == 422
    api.patch(f"/api/board/matches/{created['id']}", json={"discipline": "Carbine", "event_date": "2026-11-21", "start_time": "10:00",
                                                           "results_url": "https://practiscore.com/results/new/999"})
    photos = api.post(f"/api/board/matches/{created['id']}/photos",
                      files=[("files", ("a.png", PNG, "image/png")), ("files", ("b.png", PNG, "image/png"))]).json()["photos"]
    assert len(photos) == 2
    api.post(f"/api/board/matches/{created['id']}/photos/reorder", json={"ids": [photos[1]["id"], photos[0]["id"]]})
    api.patch(f"/api/board/match-photos/{photos[0]['id']}", json={"caption": "Stage 1"})

    public = new_api().get("/api/public/matches").json()
    disciplines = [d["discipline"] for d in public["disciplines"]]
    assert disciplines == ["Defensive Pistol", "Carbine"]
    carbine = public["disciplines"][1]["matches"][0]
    assert carbine["results_url"] == "https://practiscore.com/results/new/999"
    assert [p["id"] for p in carbine["photos"]] == [photos[1]["id"], photos[0]["id"]]
    pistol = public["disciplines"][0]["matches"]
    assert pistol[0]["results_url"] == "https://practiscore.com/results/new/325886"
    assert new_api().get(f"/api/public/match-photos/{photos[0]['id']}").content == PNG

    api.delete(f"/api/board/match-photos/{photos[0]['id']}")
    assert api.delete(f"/api/board/matches/{created['id']}").status_code == 200
    assert [d["discipline"] for d in new_api().get("/api/public/matches").json()["disciplines"]] == ["Defensive Pistol"]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "match.deleted"))


def test_seed_matches_have_times():
    from tests.conftest import seed_migration

    assert seed_migration.MATCHES[0][1] == time(13, 0)
