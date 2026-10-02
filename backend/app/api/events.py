"""Calendar events (with monthly recurrence) and matches (with photo galleries)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.cms import api_url, stream_public
from app.api.deps import BoardAuth, get_db, request_context, require_permission
from app.core.permissions import Permission
from app.core.ratelimit import rate_limit
from app.core.timeutil import club_local_to_utc, club_today, to_club_local
from app.models import EVENT_CATEGORIES, CalendarEvent, CalendarSeries, Match, MatchPhoto
from app.schemas.common import APIModel, Message
from app.services import audit, recurrence, uploads
from app.services.html import is_safe_http_url, sanitize_html
from app.services.storage import delete_quietly, get_storage, new_key

public_router = APIRouter(prefix="/api/public", tags=["public"], dependencies=[Depends(rate_limit("public-events", 300, 60))])
board_router = APIRouter(prefix="/api/board", tags=["board: calendar & matches"])

can_calendar = require_permission(Permission.CALENDAR_MANAGE)
can_matches = require_permission(Permission.MATCHES_MANAGE)

Category = Literal["match", "member", "meeting", "event", "closure"]


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


class EventOut(BaseModel):
    id: int
    title: str
    starts_at: datetime
    ends_at: datetime | None
    local_date: date
    local_time: str | None
    local_end_time: str | None
    all_day: bool
    category: str
    description_html: str | None
    link_url: str | None
    link_label: str | None
    image_url: str | None
    document_url: str | None
    document_filename: str | None
    series_id: uuid.UUID | None
    recurrence_label: str | None


def event_out(event: CalendarEvent) -> EventOut:
    local = to_club_local(event.starts_at)
    local_end = to_club_local(event.ends_at) if event.ends_at else None
    return EventOut(
        id=event.id,
        title=event.title,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        local_date=local.date(),
        local_time=None if event.all_day else local.strftime("%H:%M"),
        local_end_time=local_end.strftime("%H:%M") if local_end and not event.all_day else None,
        all_day=event.all_day,
        category=event.category,
        description_html=event.description_html,
        link_url=event.link_url,
        link_label=event.link_label,
        image_url=api_url(f"/api/public/calendar/{event.id}/image?v={event.image_key.rsplit('/', 1)[-1]}") if event.image_key else None,
        document_url=api_url(f"/api/public/calendar/{event.id}/document") if event.document_key else None,
        document_filename=event.document_filename,
        series_id=event.series_id,
        recurrence_label=event.recurrence_label,
    )


def _range(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    start = start or (club_today() - timedelta(days=31))
    end = end or (start + timedelta(days=400))
    if end < start or (end - start).days > 800:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Choose a date range of at most two years.")
    return club_local_to_utc(start, time.min), club_local_to_utc(end, time.max)


def _events_between(db: Session, start: date | None, end: date | None) -> list[CalendarEvent]:
    lower, upper = _range(start, end)
    return list(db.scalars(
        select(CalendarEvent).where(CalendarEvent.starts_at.between(lower, upper)).order_by(CalendarEvent.starts_at)
    ))


@public_router.get("/calendar", response_model=list[EventOut])
def public_calendar(start: date | None = None, end: date | None = None, db: Session = Depends(get_db)) -> list[EventOut]:
    return [event_out(e) for e in _events_between(db, start, end)]


@public_router.get("/calendar/{event_id}", response_model=EventOut)
def public_event(event_id: int, db: Session = Depends(get_db)) -> EventOut:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This event no longer exists.")
    return event_out(event)


@public_router.get("/calendar/{event_id}/image")
def event_image(event_id: int, db: Session = Depends(get_db)) -> Response:
    event = db.get(CalendarEvent, event_id)
    if event is None or not event.image_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found.")
    return stream_public(event.image_key, event.image_mime or "image/jpeg", cache="public, max-age=86400")


@public_router.get("/calendar/{event_id}/document")
def event_document(event_id: int, db: Session = Depends(get_db)) -> Response:
    event = db.get(CalendarEvent, event_id)
    if event is None or not event.document_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return stream_public(event.document_key, "application/pdf", filename=event.document_filename)


@board_router.get("/calendar", response_model=list[EventOut])
def board_calendar(start: date | None = None, end: date | None = None, auth: BoardAuth = Depends(can_calendar),
                   db: Session = Depends(get_db)) -> list[EventOut]:
    return [event_out(e) for e in _events_between(db, start, end)]


def _parse_time(value: str, label: str) -> time | None:
    value = value.strip()
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{label} must be a time like 13:00.") from exc


async def _apply_event_form(
    db: Session,
    event: CalendarEvent,
    *,
    title: str,
    event_date: date,
    start_time: str,
    end_time: str,
    all_day: bool,
    category: str,
    description_html: str,
    link_url: str,
    link_label: str,
    image: UploadFile | None,
    document: UploadFile | None,
    remove_image: bool,
    remove_document: bool,
) -> list[str]:
    """Returns storage keys to delete after the transaction commits."""
    if category not in EVENT_CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown category.")
    if not title.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A title is required.")
    link_url = link_url.strip()
    if link_url and not is_safe_http_url(link_url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The link must start with http:// or https://")
    start = _parse_time(start_time, "Start time")
    end = _parse_time(end_time, "End time")
    if not all_day and start is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Enter a start time or mark the event all day.")
    event.title = title.strip()[:200]
    event.all_day = all_day
    event.starts_at = club_local_to_utc(event_date, time(0, 0) if all_day else start)  # type: ignore[arg-type]
    event.ends_at = club_local_to_utc(event_date, end) if end and not all_day else None
    if event.ends_at and event.ends_at < event.starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The end time must be after the start time.")
    event.category = category
    event.description_html = sanitize_html(description_html) or None
    event.link_url = link_url or None
    event.link_label = (link_label.strip() or None) if link_url else None

    stale: list[str] = []
    if image is not None and image.filename:
        upload = await uploads.validate_upload(image, uploads.WEB_IMAGE_TYPES, max_bytes=5 * 1024 * 1024, label="Event image")
        key = new_key("public/calendar", upload.extension)
        get_storage().put(key, upload.data, upload.mime_type)
        stale.append(event.image_key or "")
        event.image_key, event.image_filename, event.image_mime = key, upload.original_filename, upload.mime_type
    elif remove_image and event.image_key:
        stale.append(event.image_key)
        event.image_key = event.image_filename = event.image_mime = None
    if document is not None and document.filename:
        upload = await uploads.validate_upload(document, uploads.PDF_ONLY, label="Event document")
        key = new_key("public/calendar", upload.extension)
        get_storage().put(key, upload.data, upload.mime_type)
        stale.append(event.document_key or "")
        event.document_key, event.document_filename = key, upload.original_filename
    elif remove_document and event.document_key:
        stale.append(event.document_key)
        event.document_key = event.document_filename = None
    return [k for k in stale if k]


@board_router.post("/calendar", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event(
    request: Request,
    title: str = Form(...),
    event_date: date = Form(...),
    start_time: str = Form(default=""),
    end_time: str = Form(default=""),
    all_day: bool = Form(default=False),
    category: Category = Form(default="event"),
    description_html: str = Form(default=""),
    link_url: str = Form(default=""),
    link_label: str = Form(default=""),
    image: UploadFile | None = File(default=None),
    document: UploadFile | None = File(default=None),
    auth: BoardAuth = Depends(can_calendar),
    db: Session = Depends(get_db),
) -> EventOut:
    event = CalendarEvent()
    await _apply_event_form(db, event, title=title, event_date=event_date, start_time=start_time, end_time=end_time,
                            all_day=all_day, category=category, description_html=description_html, link_url=link_url,
                            link_label=link_label, image=image, document=document, remove_image=False, remove_document=False)
    db.add(event)
    db.flush()
    audit.record(db, actor=auth.person, action="calendar.event_created", entity_type="calendar_event", entity_id=event.id,
                 summary=f"{event.title} on {event_date.isoformat()}", context=request_context(request))
    db.commit()
    return event_out(event)


@board_router.patch("/calendar/{event_id}", response_model=EventOut)
async def update_event(
    event_id: int,
    request: Request,
    title: str = Form(...),
    event_date: date = Form(...),
    start_time: str = Form(default=""),
    end_time: str = Form(default=""),
    all_day: bool = Form(default=False),
    category: Category = Form(default="event"),
    description_html: str = Form(default=""),
    link_url: str = Form(default=""),
    link_label: str = Form(default=""),
    remove_image: bool = Form(default=False),
    remove_document: bool = Form(default=False),
    image: UploadFile | None = File(default=None),
    document: UploadFile | None = File(default=None),
    auth: BoardAuth = Depends(can_calendar),
    db: Session = Depends(get_db),
) -> EventOut:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found.")
    stale = await _apply_event_form(db, event, title=title, event_date=event_date, start_time=start_time, end_time=end_time,
                                    all_day=all_day, category=category, description_html=description_html, link_url=link_url,
                                    link_label=link_label, image=image, document=document, remove_image=remove_image,
                                    remove_document=remove_document)
    audit.record(db, actor=auth.person, action="calendar.event_updated", entity_type="calendar_event", entity_id=event.id,
                 summary=event.title, context=request_context(request))
    db.commit()
    for key in stale:
        delete_quietly(key)
    return event_out(event)


@board_router.delete("/calendar/{event_id}", response_model=Message)
def delete_event(event_id: int, request: Request, auth: BoardAuth = Depends(can_calendar), db: Session = Depends(get_db)) -> Message:
    event = db.get(CalendarEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Event not found.")
    keys = [event.image_key, event.document_key]
    audit.record(db, actor=auth.person, action="calendar.event_deleted", entity_type="calendar_event", entity_id=event.id,
                 summary=event.title, context=request_context(request))
    db.delete(event)
    db.commit()
    for key in keys:
        delete_quietly(key)
    return Message(message="Event deleted.")


class SeriesRequest(APIModel):
    title: str = Field(min_length=1, max_length=200)
    weekday: int = Field(ge=0, le=6)
    nth: int = Field(ge=1, le=5)
    start_time: time
    end_time: time | None = None
    category: Category = "event"
    description_html: str = Field(default="", max_length=20_000)
    start_year: int = Field(ge=2000, le=2100)
    start_month: int = Field(ge=1, le=12)
    month_count: int = Field(ge=1, le=36)


@board_router.post("/calendar/series/preview")
def preview_series(payload: SeriesRequest, auth: BoardAuth = Depends(can_calendar)) -> dict[str, object]:
    dates = recurrence.series_dates(weekday=payload.weekday, nth=payload.nth, start_year=payload.start_year,
                                    start_month=payload.start_month, month_count=payload.month_count)
    return {"label": recurrence.describe_recurrence(payload.nth, payload.weekday), "dates": [d.isoformat() for d in dates]}


@board_router.post("/calendar/series", status_code=status.HTTP_201_CREATED)
def create_series(payload: SeriesRequest, request: Request, auth: BoardAuth = Depends(can_calendar), db: Session = Depends(get_db)) -> dict[str, object]:
    if payload.end_time and payload.end_time <= payload.start_time:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The end time must be after the start time.")
    label = recurrence.describe_recurrence(payload.nth, payload.weekday)
    series = CalendarSeries(title=payload.title.strip(), nth=payload.nth, weekday=payload.weekday,
                            start_time=payload.start_time, label=label, created_by_id=auth.person.id)
    db.add(series)
    db.flush()
    dates = recurrence.series_dates(weekday=payload.weekday, nth=payload.nth, start_year=payload.start_year,
                                    start_month=payload.start_month, month_count=payload.month_count)
    description = sanitize_html(payload.description_html) or None
    for day in dates:
        db.add(CalendarEvent(
            title=series.title, starts_at=club_local_to_utc(day, payload.start_time),
            ends_at=club_local_to_utc(day, payload.end_time) if payload.end_time else None,
            category=payload.category, description_html=description, series_id=series.id, recurrence_label=label,
        ))
    audit.record(db, actor=auth.person, action="calendar.series_created", entity_type="calendar_series", entity_id=series.id,
                 summary=f"{series.title}: {label}, {len(dates)} events", context=request_context(request))
    db.commit()
    return {"series_id": str(series.id), "label": label, "created": len(dates)}


@board_router.delete("/calendar/series/{series_id}", response_model=Message)
def delete_series(series_id: uuid.UUID, request: Request, scope: Literal["future", "all"] = "future",
                  auth: BoardAuth = Depends(can_calendar), db: Session = Depends(get_db)) -> Message:
    series = db.get(CalendarSeries, series_id)
    if series is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Series not found.")
    query = select(CalendarEvent).where(CalendarEvent.series_id == series_id)
    if scope == "future":
        query = query.where(CalendarEvent.starts_at >= club_local_to_utc(club_today(), time.min))
    events = db.scalars(query).all()
    keys = [k for e in events for k in (e.image_key, e.document_key) if k]
    for event in events:
        db.delete(event)
    audit.record(db, actor=auth.person, action="calendar.series_deleted", entity_type="calendar_series", entity_id=series_id,
                 summary=f"Deleted {len(events)} {scope} events of {series.title}", context=request_context(request))
    db.commit()
    for key in keys:
        delete_quietly(key)
    return Message(message=f"Deleted {len(events)} events.")


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


class PhotoOut(BaseModel):
    id: int
    url: str
    caption: str | None
    sort_order: int


class MatchOut(BaseModel):
    id: int
    discipline: str
    event_date: date
    start_time: str | None
    notes: str | None
    results_url: str | None
    sort_order: int
    photos: list[PhotoOut]


def match_out(match: Match) -> MatchOut:
    return MatchOut(
        id=match.id, discipline=match.discipline, event_date=match.event_date,
        start_time=match.start_time.strftime("%H:%M") if match.start_time else None,
        notes=match.notes, results_url=match.results_url, sort_order=match.sort_order,
        photos=[PhotoOut(id=p.id, url=api_url(f"/api/public/match-photos/{p.id}"), caption=p.caption, sort_order=p.sort_order)
                for p in match.photos],
    )


def _ordered_matches(db: Session, year: int | None) -> list[Match]:
    query = select(Match)
    if year:
        query = query.where(func.extract("year", Match.event_date) == year)
    return list(db.scalars(query.order_by(Match.sort_order, Match.event_date, Match.id)))


@public_router.get("/matches")
def public_matches(year: int | None = None, db: Session = Depends(get_db)) -> dict[str, object]:
    """Matches grouped by discipline, each discipline in first-appearance order."""
    groups: dict[str, list[MatchOut]] = {}
    for match in _ordered_matches(db, year):
        groups.setdefault(match.discipline, []).append(match_out(match))
    years = sorted({int(y) for y in db.scalars(select(func.extract("year", Match.event_date)).distinct())}, reverse=True)
    return {"disciplines": [{"discipline": d, "matches": m} for d, m in groups.items()], "years": years}


@public_router.get("/match-photos/{photo_id}")
def match_photo(photo_id: int, db: Session = Depends(get_db)) -> Response:
    photo = db.get(MatchPhoto, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Photo not found.")
    return stream_public(photo.storage_key, photo.mime_type, cache="public, max-age=86400")


class MatchIn(APIModel):
    discipline: str = Field(default="Defensive Pistol", min_length=1, max_length=120)
    event_date: date
    start_time: time | None = None
    notes: str | None = Field(default=None, max_length=2000)
    results_url: str | None = Field(default=None, max_length=500)


def _validated_results_url(value: str | None) -> str | None:
    value = (value or "").strip() or None
    if value and not is_safe_http_url(value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The results link must start with https://")
    return value


@board_router.get("/matches", response_model=list[MatchOut])
def board_matches(auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> list[MatchOut]:
    return [match_out(m) for m in _ordered_matches(db, None)]


@board_router.post("/matches", response_model=MatchOut, status_code=status.HTTP_201_CREATED)
def create_match(payload: MatchIn, request: Request, auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> MatchOut:
    max_order = db.scalar(select(func.coalesce(func.max(Match.sort_order), 0))) or 0
    match = Match(discipline=payload.discipline.strip(), event_date=payload.event_date, start_time=payload.start_time,
                  notes=(payload.notes or "").strip() or None, results_url=_validated_results_url(payload.results_url),
                  sort_order=max_order + 10)
    db.add(match)
    db.flush()
    audit.record(db, actor=auth.person, action="match.created", entity_type="match", entity_id=match.id,
                 summary=f"{match.discipline} on {match.event_date}", context=request_context(request))
    db.commit()
    return match_out(match)


@board_router.patch("/matches/{match_id}", response_model=MatchOut)
def update_match(match_id: int, payload: MatchIn, request: Request, auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> MatchOut:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Match not found.")
    match.discipline = payload.discipline.strip()
    match.event_date = payload.event_date
    match.start_time = payload.start_time
    match.notes = (payload.notes or "").strip() or None
    match.results_url = _validated_results_url(payload.results_url)
    audit.record(db, actor=auth.person, action="match.updated", entity_type="match", entity_id=match.id,
                 summary=f"{match.discipline} on {match.event_date}", context=request_context(request))
    db.commit()
    return match_out(match)


@board_router.delete("/matches/{match_id}", response_model=Message)
def delete_match(match_id: int, request: Request, auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> Message:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Match not found.")
    keys = [p.storage_key for p in match.photos]
    audit.record(db, actor=auth.person, action="match.deleted", entity_type="match", entity_id=match.id,
                 summary=f"{match.discipline} on {match.event_date}", context=request_context(request))
    db.delete(match)
    db.commit()
    for key in keys:
        delete_quietly(key)
    return Message(message="Match deleted.")


class OrderRequest(APIModel):
    ids: list[int]


@board_router.post("/matches/reorder", response_model=Message)
def reorder_matches(payload: OrderRequest, auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> Message:
    matches = {m.id: m for m in db.scalars(select(Match).where(Match.id.in_(payload.ids)))}
    for index, match_id in enumerate(payload.ids):
        if match_id in matches:
            matches[match_id].sort_order = (index + 1) * 10
    audit.record(db, actor=auth.person, action="match.reordered", entity_type="match")
    db.commit()
    return Message(message="Order saved.")


@board_router.post("/matches/{match_id}/photos", response_model=MatchOut, status_code=status.HTTP_201_CREATED)
async def add_photos(match_id: int, request: Request, files: list[UploadFile] = File(...), auth: BoardAuth = Depends(can_matches),
                     db: Session = Depends(get_db)) -> MatchOut:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Match not found.")
    if len(files) > 20:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Upload at most 20 photos at a time.")
    next_order = max((p.sort_order for p in match.photos), default=0)
    validated = [await uploads.validate_upload(f, uploads.WEB_IMAGE_TYPES, max_bytes=8 * 1024 * 1024, label=f"Photo {f.filename}") for f in files]
    for upload in validated:
        key = new_key(f"public/match-photos/{match.id}", upload.extension)
        get_storage().put(key, upload.data, upload.mime_type)
        next_order += 10
        match.photos.append(MatchPhoto(storage_key=key, original_filename=upload.original_filename,
                                       mime_type=upload.mime_type, sort_order=next_order))
    audit.record(db, actor=auth.person, action="match.photos_added", entity_type="match", entity_id=match.id,
                 details={"count": len(validated)}, context=request_context(request))
    db.commit()
    db.refresh(match)
    return match_out(match)


class PhotoUpdate(APIModel):
    caption: str | None = Field(default=None, max_length=255)


@board_router.patch("/match-photos/{photo_id}", response_model=PhotoOut)
def update_photo(photo_id: int, payload: PhotoUpdate, auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> PhotoOut:
    photo = db.get(MatchPhoto, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Photo not found.")
    photo.caption = (payload.caption or "").strip() or None
    db.commit()
    return PhotoOut(id=photo.id, url=api_url(f"/api/public/match-photos/{photo.id}"), caption=photo.caption, sort_order=photo.sort_order)


@board_router.delete("/match-photos/{photo_id}", response_model=Message)
def delete_photo(photo_id: int, request: Request, auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> Message:
    photo = db.get(MatchPhoto, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Photo not found.")
    key = photo.storage_key
    audit.record(db, actor=auth.person, action="match.photo_removed", entity_type="match", entity_id=photo.match_id,
                 context=request_context(request))
    db.execute(delete(MatchPhoto).where(MatchPhoto.id == photo_id))
    db.commit()
    delete_quietly(key)
    return Message(message="Photo removed.")


@board_router.post("/matches/{match_id}/photos/reorder", response_model=MatchOut)
def reorder_photos(match_id: int, payload: OrderRequest, auth: BoardAuth = Depends(can_matches), db: Session = Depends(get_db)) -> MatchOut:
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Match not found.")
    photos = {p.id: p for p in match.photos}
    for index, photo_id in enumerate(payload.ids):
        if photo_id in photos:
            photos[photo_id].sort_order = (index + 1) * 10
    db.commit()
    db.refresh(match)
    return match_out(match)
