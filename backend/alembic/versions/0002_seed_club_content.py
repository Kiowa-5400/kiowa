"""Seed the club's existing content, ported from kiowa-gun.

Page text, officers, contact details, range rules, the 2026 match schedule
(with PractiScore result links) and the recurring calendar series come from
kiowa-gun's D1 seed migrations (0002, 0027, 0031, 0035) and the current kiowa
public pages, so the new site launches with the same content. Everything here
is editable afterwards from the board app.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02
"""

from __future__ import annotations

import calendar as cal
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLUB_TZ = ZoneInfo("America/Chicago")

RANGE_RULES = [
    "Range flag at gate must be raised anytime you are on the property. Range flag at firing line must be raised when shooting on the line or downrange.",
    "All shooting on rifle ranges MUST be done from the permanent firing line.",
    "I will not shoot when work crews are on the range.",
    "I will follow all of the safety rules and guidelines I have been taught about safe gunhandling. I am responsible for my guest's actions while on property.",
    "I will NOT shoot center fire rifles, including .223 pistols, toward or in pistol ranges #1 and #2.",
    "I will follow the club calendar, as scheduled events will take precedence.",
    "I will not shoot with artificial lighting.",
    "I will take all my targets and trash I brought to the range home, or deposit in trash cans provided. I WILL NOT LEAVE MY TARGETS ON THE BACKER BOARDS.",
    "I will only shoot at targets that are safe, NOT trash cans, rocks, or other items that may cause ricochets.",
    "During scheduled shoots, modified rules may apply.",
    "No hunting of any kind is allowed on club property.",
    "Shotgun shooting is NOT ALLOWED on club property. This includes handguns while shooting shotshells.",
    "A member must accompany guests at all times.",
    "Vehicles are allowed to be driven to the backstops to set up or check targets, provided they stay on the rock. No vehicles are allowed behind the backstops.",
    "No alcoholic beverages are allowed on club property at any time.",
    "Eye and ear protection is required at all matches. We recommend using them whenever you are shooting.",
    "Do not leave live rounds lying on the range. Dispose of them in the misfire container located at the end of the backstop between ranges #1 and #2.",
    "The use of binary explosives is prohibited. (Tannerite, Shockwave, etc.)",
]

AGREEMENT_CLAUSE = (
    "I have read these rules and I agree to abide by these rules. As safety is our primary concern, I understand that any "
    "violation of these rules by me or my guests could result in termination of my membership. I have read, understand, "
    "and agree to follow the Kiowa Gun Club Range Rules."
)

REPORTING_CLAUSE = (
    "If you see someone violate these rules or act in an unsafe manner, it is suggested that you approach them in a "
    "non-threatening manner and bring the violation to their attention. If you are not satisfied that they understand and "
    "will correct their actions, contact a club officer, and a review of the incident will be made by the board. As a "
    "member, you have the right to ask to see their membership card."
)

SECTIONS: list[tuple[str, str, str, str | None, str]] = [
    # (page_slug, section_key, label, heading, body_html)
    ("home", "hero", "Hero banner", "Built for neighbors, families, and responsible shooters.",
     "<p>A community range rooted in the heart of Kansas, where safety, tradition, and good company still matter.</p>"),
    ("home", "welcome", "Welcome", "Welcome!",
     "<p>The Kiowa Gun Club, one of the oldest established clubs in the central Kansas region, is a membership-driven club. "
     "The club is proud to be a National Rifle Association affiliated club. Current active membership in the NRA is a "
     "requirement of club membership. Membership dues are $150 annually; the membership period is from August 1st to July 31st.</p>"),
    ("home", "notice", "Membership notice", "Membership Renewals & Waiting List",
     "<p>Renewing your membership or applying for the waiting list? Read the Range Rules and complete the application "
     "online, including your NRA proof and any required background-check documentation.</p>"),
    ("home", "matches_teaser", "Matches teaser", "Scheduled Pistol Shoots 2026",
     "<p>Defensive pistol shoots are held on the second Saturday of each month during the season.</p>"
     "<p>First-time shooters shoot free; following shoots are $15, which includes everyone in your immediate family. "
     "Everyone (members and non-members) is welcome.</p>"
     "<p>Club members are also invited to join us the 4th Tuesday of each month for a fun evening of shooting, starting at 6pm.</p>"),
    ("home", "safety", "Gun safety rules", "Jeff Cooper's Rules of Gun Safety",
     "<ol><li>All guns are always loaded.</li><li>Never let the muzzle cover anything you are not willing to destroy.</li>"
     "<li>Keep your finger off the trigger until your sights are on the target.</li><li>Be sure of your target.</li></ol>"),
    ("about", "intro", "Introduction", "About Kiowa Gun Club",
     "<p>Kiowa Gun Club is a membership-driven club serving the Great Bend, Kansas community with a focus on safe, "
     "responsible range use and organized shooting activities.</p>"),
    ("about", "club", "The club", "A community range in central Kansas",
     "<p>Kiowa Gun Club is one of the oldest established clubs in the central Kansas region and is affiliated with the "
     "National Rifle Association. Club membership requires active NRA membership.</p>"
     "<p>Membership dues are $150 annually, with the membership year running from August 1 through July 31. Prospective "
     "new members also complete a background check and a range orientation.</p>"),
    ("about", "activities", "Range activities", "More than a monthly match",
     "<ul><li>Defensive pistol matches on the second Saturday of the month during the scheduled season.</li>"
     "<li>Member social shoots on the fourth Tuesday of each month at 6:00 PM.</li>"
     "<li>Carbine and other organized shooting events as scheduled.</li>"
     "<li>Open range use for members, subject to club rules and scheduled activities.</li></ul>"),
    ("about", "officers", "Officers", "Current Kiowa Gun Club Officers",
     "<ul><li>Lane Moore, President</li><li>Mike Ille, Vice President</li><li>Sheldon Peacock, Treasurer</li>"
     "<li>Joe Felke, Secretary</li><li>Dennis Kephart, Range Officer</li></ul>"
     "<p><strong>Kiowa Gun Club Inc. is a private shooting club for members and guests only.</strong></p>"),
    ("contact", "intro", "Introduction", "Contact Kiowa Gun Club",
     "<p>Questions about membership, matches, the range, or club activities? Reach out using the information below.</p>"),
    ("contact", "membership_contacts", "Membership contacts", "Membership questions",
     "<ul><li>Sheldon Peacock: <a href=\"tel:+16202828554\">(620) 282-8554</a></li>"
     "<li>Dennis Kephart: <a href=\"tel:+16206173053\">(620) 617-3053</a></li></ul>"),
    ("membership", "terms", "Membership terms", "Membership Info",
     "<p>Membership dues are $150 annually, due August 1st of each year. Failure to pay dues by September 10th will "
     "result in the termination of your membership.</p>"
     "<p>Members must be current members of the NRA and show proof of unexpired NRA membership.</p>"
     "<p>All new members are required to complete a range orientation before membership is approved.</p>"
     "<p>Due to a limited number of memberships, new members join from the waiting list. Apply for the waiting list online.</p>"),
    ("membership", "background_check", "Background check policy", "Attention Prospective Members",
     "<p>The directors of the Kiowa Gun Club require prospective members to complete a criminal background check, at "
     "the prospective member's expense, through the firm Criminal Watch Dog. The nationwide background check is the only "
     "background check accepted by the club.</p>"
     "<p>Upload the cover page of your completed background check with your online waiting-list application. (You may "
     "also mail it to Kiowa Gun Club, Inc., P.O. Box 562, Great Bend, KS 67530.) Applicants have 10 calendar days from "
     "the time they are contacted by the club to provide the completed background check, or their name is removed from "
     "the waiting list.</p>"
     "<p>If you hold a current concealed carry permit, it is accepted the same as a background check.</p>"
     "<p>Once the background check is received, the board of directors reviews it to determine whether the applicant is "
     "accepted for membership. Accepted applicants complete a safety orientation at the range and pay the $150 dues. "
     "Membership in the NRA is required.</p>"
     "<p>Background checks are available at <a href=\"https://www.criminalwatchdog.com\">criminalwatchdog.com</a>.</p>"),
    ("membership", "orientation", "Orientation (included in approval emails)", "Range Orientation",
     "<p>New members must attend a mandatory in-person range orientation. Contact the club to schedule yours after your "
     "dues are paid.</p>"),
    ("rules", "intro", "Introduction", "Range Rules",
     "<p>The club establishes the following regulations for safe and responsible range use.</p>"),
    ("rules", "dues_policy", "Dues and orientation policy", "Dues & Orientation",
     "<p>Membership dues are due August 1st of each year. FAILURE TO PAY DUES BY SEPTEMBER 10TH WILL RESULT IN "
     "TERMINATION OF YOUR MEMBERSHIP. At this time dues are $150 annually.</p>"
     "<p>All new members must complete a range safety orientation before they are issued their membership card.</p>"),
    ("calendar", "intro", "Introduction", "Club Calendar",
     "<p>See what's happening at the range. Select an event for details. Scheduled events take precedence over open "
     "range use, and times are subject to change.</p>"),
    ("matches", "intro", "Introduction", "2026 Defensive Pistol Matches",
     "<p>Defensive pistol shoots are held on the second Saturday of each month during the season (subject to change). "
     "Everyone (members and non-members) is welcome.</p>"),
    ("matches", "participation", "Participation", "Match fees",
     "<p>First-time shooters shoot free. Following shoots are $15, which includes everyone in your immediate family.</p>"
     "<p>Results are posted on PractiScore. Select a match date to see its results.</p>"),
]

MATCHES = [
    (date(2026, 3, 14), time(13, 0), None, "https://practiscore.com/results/new/325886"),
    (date(2026, 4, 11), time(13, 0), None, "https://practiscore.com/results/new/329673"),
    (date(2026, 5, 9), time(9, 0), None, "https://practiscore.com/results/new/333967"),
    (date(2026, 6, 13), time(8, 0), "Great Plains Speed Shooting Championship", None),
    (date(2026, 7, 11), time(9, 0), None, None),
    (date(2026, 8, 8), time(9, 0), None, None),
    (date(2026, 9, 12), time(9, 0), None, None),
    (date(2026, 10, 10), time(9, 0), None, None),
    (date(2026, 11, 14), time(13, 0), None, None),
]

POSITIONS = ["Vice President", "Treasurer", "Secretary", "Range Officer", "Membership Chair"]

PISTOL_SERIES = uuid.UUID("6f1d2a7e-3c4b-4e1a-9a52-2b2f0d6a1001")
SOCIAL_SERIES = uuid.UUID("6f1d2a7e-3c4b-4e1a-9a52-2b2f0d6a1002")


def _nth_weekday(year: int, month: int, py_weekday: int, nth: int) -> date:
    days = [d for d in range(1, cal.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == py_weekday]
    return date(year, month, days[nth - 1])


def _months(start: tuple[int, int], count: int) -> list[tuple[int, int]]:
    year, month = start
    out = []
    for _ in range(count):
        out.append((year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


def _utc(day: date, at: time) -> datetime:
    return datetime.combine(day, at, tzinfo=CLUB_TZ).astimezone(UTC)


def upgrade() -> None:
    site_settings = sa.table(
        "site_settings",
        sa.column("id", sa.Integer), sa.column("site_title", sa.String), sa.column("site_subtitle", sa.String),
        sa.column("contact_email", sa.String), sa.column("contact_phone", sa.String),
        sa.column("mailing_address", sa.Text), sa.column("physical_address", sa.Text), sa.column("map_url", sa.String),
        sa.column("footer_links", postgresql.JSONB), sa.column("dues_amount", sa.Numeric),
        sa.column("cleanup_discount_amount", sa.Numeric), sa.column("renewal_cutoff_month", sa.Integer),
        sa.column("renewal_cutoff_day", sa.Integer), sa.column("accepting_waiting_list", sa.Boolean),
        sa.column("background_check_url", sa.String), sa.column("rules_version", sa.String),
        sa.column("range_rules", postgresql.JSONB), sa.column("rules_agreement_clause", sa.Text),
        sa.column("rules_reporting_clause", sa.Text),
    )
    op.bulk_insert(site_settings, [{
        "id": 1,
        "site_title": "Kiowa Gun Club",
        "site_subtitle": "Great Bend, Kansas",
        "contact_email": "kiowa369@outlook.com",
        "contact_phone": None,
        "mailing_address": "PO Box 562\nGreat Bend, KS 67530",
        "physical_address": "369 SW 50 Ave\nGreat Bend, KS 67530",
        "map_url": "https://www.google.com/maps/search/?api=1&query=369+SW+50+Ave%2C+Great+Bend%2C+KS+67530",
        "footer_links": [],
        "dues_amount": 150,
        "cleanup_discount_amount": 0,
        "renewal_cutoff_month": 9,
        "renewal_cutoff_day": 10,
        "accepting_waiting_list": True,
        "background_check_url": "https://www.criminalwatchdog.com",
        "rules_version": "2026-10-01",
        "range_rules": RANGE_RULES,
        "rules_agreement_clause": AGREEMENT_CLAUSE,
        "rules_reporting_clause": REPORTING_CLAUSE,
    }])

    page_sections = sa.table(
        "page_sections",
        sa.column("page_slug", sa.String), sa.column("section_key", sa.String), sa.column("label", sa.String),
        sa.column("heading", sa.String), sa.column("body_html", sa.Text), sa.column("sort_order", sa.Integer),
    )
    rows = []
    order: dict[str, int] = {}
    for slug, key, label, heading, body in SECTIONS:
        order[slug] = order.get(slug, 0) + 10
        rows.append({"page_slug": slug, "section_key": key, "label": label, "heading": heading, "body_html": body,
                     "sort_order": order[slug]})
    op.bulk_insert(page_sections, rows)

    op.bulk_insert(sa.table("position_options", sa.column("label", sa.String)), [{"label": p} for p in POSITIONS])

    matches = sa.table(
        "matches",
        sa.column("discipline", sa.String), sa.column("event_date", sa.Date), sa.column("start_time", sa.Time),
        sa.column("notes", sa.Text), sa.column("results_url", sa.String), sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(matches, [
        {"discipline": "Defensive Pistol", "event_date": d, "start_time": t, "notes": n, "results_url": u, "sort_order": (i + 1) * 10}
        for i, (d, t, n, u) in enumerate(MATCHES)
    ])

    series = sa.table(
        "calendar_series",
        sa.column("id", sa.Uuid), sa.column("title", sa.String), sa.column("nth", sa.Integer),
        sa.column("weekday", sa.Integer), sa.column("start_time", sa.Time), sa.column("label", sa.String),
    )
    op.bulk_insert(series, [
        {"id": PISTOL_SERIES, "title": "Defensive Pistol Shoot", "nth": 2, "weekday": 6, "start_time": time(13, 0),
         "label": "Every 2nd Saturday of the month"},
        {"id": SOCIAL_SERIES, "title": "Club Member Shooting Session", "nth": 4, "weekday": 2, "start_time": time(18, 0),
         "label": "Every 4th Tuesday of the month"},
    ])

    events = sa.table(
        "calendar_events",
        sa.column("title", sa.String), sa.column("starts_at", sa.DateTime(timezone=True)), sa.column("category", sa.String),
        sa.column("series_id", sa.Uuid), sa.column("recurrence_label", sa.String),
    )
    match_times = {d: t for d, t, _, _ in MATCHES}
    event_rows = []
    # Same months kiowa-gun seeded (August 2026 - December 2027). A pistol shoot
    # on a scheduled match date uses that match's start time.
    for year, month in _months((2026, 8), 17):
        shoot_day = _nth_weekday(year, month, 5, 2)  # Python weekday 5 = Saturday
        event_rows.append({"title": "Defensive Pistol Shoot", "starts_at": _utc(shoot_day, match_times.get(shoot_day, time(13, 0))),
                           "category": "match", "series_id": PISTOL_SERIES, "recurrence_label": "Every 2nd Saturday of the month"})
        social_day = _nth_weekday(year, month, 1, 4)  # Python weekday 1 = Tuesday
        event_rows.append({"title": "Club Member Shooting Session", "starts_at": _utc(social_day, time(18, 0)),
                           "category": "member", "series_id": SOCIAL_SERIES, "recurrence_label": "Every 4th Tuesday of the month"})
    op.bulk_insert(events, event_rows)


def downgrade() -> None:
    op.execute("DELETE FROM calendar_events WHERE series_id IN ('%s', '%s')" % (PISTOL_SERIES, SOCIAL_SERIES))
    op.execute("DELETE FROM calendar_series WHERE id IN ('%s', '%s')" % (PISTOL_SERIES, SOCIAL_SERIES))
    op.execute("DELETE FROM matches")
    op.execute("DELETE FROM position_options")
    op.execute("DELETE FROM page_sections")
    op.execute("DELETE FROM site_settings WHERE id = 1")
