"""Public website content (read) and the board CMS (write)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import BoardAuth, get_db, request_context, require_permission
from app.core.config import get_settings
from app.core.permissions import Permission
from app.core.ratelimit import rate_limit
from app.core.timeutil import club_today
from app.models import SITE_IMAGE_KEYS, EmailAsset, PageSection, PublicDocument, SiteImage, SiteSettings
from app.schemas.common import APIModel, Message
from app.services import audit, membership, uploads
from app.services.html import is_safe_http_url, sanitize_html
from app.services.storage import StoredObjectNotFound, delete_quietly, get_storage, new_key

public_router = APIRouter(prefix="/api/public", tags=["public"], dependencies=[Depends(rate_limit("public", 300, 60))])
board_router = APIRouter(prefix="/api/board", tags=["board: content"])

can_edit = require_permission(Permission.CONTENT_EDIT)
can_manage_settings = require_permission(Permission.SETTINGS_MANAGE)

PAGES = {
    "home": "Home",
    "about": "About",
    "contact": "Contact",
    "membership": "Membership",
    "rules": "Range Rules",
    "calendar": "Calendar",
    "matches": "Matches",
}
IMAGE_SLOTS = {
    "logo": "Club logo (header)",
    "hero": "Home page hero photo",
    "about": "About page photo",
    "rules": "Range rules photo",
    "matches_flyer": "Matches flyer",
}
PUBLIC_CACHE = "public, max-age=300"


def api_url(path: str) -> str:
    return f"{get_settings().api_public_url.rstrip('/')}{path}"


def image_url(image: SiteImage) -> str:
    # The storage key changes on every replacement, which busts browser caches.
    return api_url(f"/api/public/images/{image.key}?v={image.storage_key.rsplit('/', 1)[-1]}")


def media_url(asset: EmailAsset) -> str:
    return api_url(f"/api/public/media/{asset.public_token}")


def stream_public(storage_key: str, mime_type: str, *, filename: str | None = None, cache: str = PUBLIC_CACHE) -> Response:
    try:
        data = get_storage().get(storage_key)
    except StoredObjectNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found.") from exc
    headers = {"Cache-Control": cache, "X-Content-Type-Options": "nosniff"}
    if filename:
        safe = "".join(c for c in filename if c.isalnum() or c in "._- ")[:100] or "download"
        headers["Content-Disposition"] = f'inline; filename="{safe}"'
    return Response(content=data, media_type=mime_type, headers=headers)


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------


class SectionOut(BaseModel):
    id: int
    section_key: str
    label: str | None
    heading: str | None
    body_html: str
    sort_order: int
    is_custom: bool
    is_visible: bool
    updated_at: datetime


class SiteOut(BaseModel):
    site_title: str
    site_subtitle: str
    contact_email: str | None
    contact_phone: str | None
    mailing_address: str | None
    physical_address: str | None
    map_url: str | None
    social: dict[str, str | None]
    footer_links: list[dict[str, str]]
    dues_amount: Decimal
    accepting_waiting_list: bool
    background_check_url: str | None
    images: dict[str, str | None]
    image_alt: dict[str, str | None]
    apply_url: str
    rules_version: str


def _site_out(db: Session) -> SiteOut:
    row = membership.site_settings(db)
    images = {img.key: img for img in db.scalars(select(SiteImage))}
    return SiteOut(
        site_title=row.site_title,
        site_subtitle=row.site_subtitle,
        contact_email=row.contact_email,
        contact_phone=row.contact_phone,
        mailing_address=row.mailing_address,
        physical_address=row.physical_address,
        map_url=row.map_url,
        social={"facebook": row.social_facebook, "instagram": row.social_instagram, "youtube": row.social_youtube},
        footer_links=list(row.footer_links or []),
        dues_amount=row.dues_amount,
        accepting_waiting_list=row.accepting_waiting_list,
        background_check_url=row.background_check_url,
        images={key: image_url(images[key]) if key in images else None for key in SITE_IMAGE_KEYS},
        image_alt={key: images[key].alt_text if key in images else None for key in SITE_IMAGE_KEYS},
        apply_url=get_settings().apply_app_url,
        rules_version=row.rules_version,
    )


@public_router.get("/site", response_model=SiteOut)
def public_site(db: Session = Depends(get_db)) -> SiteOut:
    return _site_out(db)


def _section_out(s: PageSection) -> SectionOut:
    return SectionOut(
        id=s.id, section_key=s.section_key, label=s.label, heading=s.heading, body_html=s.body_html,
        sort_order=s.sort_order, is_custom=s.is_custom, is_visible=s.is_visible, updated_at=s.updated_at,
    )


@public_router.get("/pages/{slug}", response_model=list[SectionOut])
def public_page(slug: str, db: Session = Depends(get_db)) -> list[SectionOut]:
    if slug not in PAGES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page not found.")
    rows = db.scalars(
        select(PageSection).where(PageSection.page_slug == slug, PageSection.is_visible.is_(True))
        .order_by(PageSection.sort_order, PageSection.id)
    )
    return [_section_out(s) for s in rows]


@public_router.get("/rules")
def public_rules(db: Session = Depends(get_db)) -> dict[str, object]:
    from app.api.member import rules_out

    return rules_out(db).model_dump()


class PublicDocumentOut(BaseModel):
    id: int
    title: str
    description: str | None
    category: str
    original_filename: str
    mime_type: str
    size_bytes: int
    url: str
    is_published: bool
    sort_order: int
    uploaded_at: datetime


def _public_doc_out(d: PublicDocument) -> PublicDocumentOut:
    return PublicDocumentOut(
        id=d.id, title=d.title, description=d.description, category=d.category, original_filename=d.original_filename,
        mime_type=d.mime_type, size_bytes=d.size_bytes, url=api_url(f"/api/public/documents/{d.id}/file"),
        is_published=d.is_published, sort_order=d.sort_order, uploaded_at=d.uploaded_at,
    )


@public_router.get("/documents", response_model=list[PublicDocumentOut])
def public_documents(category: str | None = None, db: Session = Depends(get_db)) -> list[PublicDocumentOut]:
    query = select(PublicDocument).where(PublicDocument.is_published.is_(True))
    if category:
        query = query.where(PublicDocument.category == category)
    return [_public_doc_out(d) for d in db.scalars(query.order_by(PublicDocument.sort_order, PublicDocument.title))]


@public_router.get("/documents/{document_id}/file")
def public_document_file(document_id: int, db: Session = Depends(get_db)) -> Response:
    document = db.get(PublicDocument, document_id)
    if document is None or not document.is_published:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return stream_public(document.storage_key, document.mime_type, filename=document.original_filename)


@public_router.get("/images/{key}")
def public_image(key: str, db: Session = Depends(get_db)) -> Response:
    image = db.get(SiteImage, key)
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No custom image for this slot.")
    return stream_public(image.storage_key, image.mime_type, cache="public, max-age=86400")


@public_router.get("/media/{token}")
def public_media(token: str, db: Session = Depends(get_db)) -> Response:
    asset = db.scalar(select(EmailAsset).where(EmailAsset.public_token == token, EmailAsset.kind == "image"))
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found.")
    return stream_public(asset.storage_key, asset.mime_type, cache="public, max-age=86400")


# ---------------------------------------------------------------------------
# Board: pages
# ---------------------------------------------------------------------------


@board_router.get("/pages")
def list_pages(auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    sections = db.scalars(select(PageSection).order_by(PageSection.page_slug, PageSection.sort_order, PageSection.id)).all()
    return [
        {"slug": slug, "label": label, "sections": [_section_out(s) for s in sections if s.page_slug == slug]}
        for slug, label in PAGES.items()
    ]


class SectionUpdate(APIModel):
    heading: str | None = Field(default=None, max_length=255)
    body_html: str = Field(default="", max_length=100_000)
    is_visible: bool = True


@board_router.put("/sections/{section_id}", response_model=SectionOut)
def update_section(section_id: int, payload: SectionUpdate, request: Request, auth: BoardAuth = Depends(can_edit),
                   db: Session = Depends(get_db)) -> SectionOut:
    section = db.get(PageSection, section_id)
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Section not found.")
    section.heading = (payload.heading or "").strip() or None
    section.body_html = sanitize_html(payload.body_html)
    section.is_visible = payload.is_visible
    section.updated_by_id = auth.person.id
    audit.record(db, actor=auth.person, action="cms.section_updated", entity_type="page_section", entity_id=section.id,
                 summary=f"Edited {PAGES.get(section.page_slug, section.page_slug)} / {section.label or section.heading or section.section_key}",
                 context=request_context(request))
    db.commit()
    return _section_out(section)


class SectionCreate(APIModel):
    heading: str | None = Field(default=None, max_length=255)
    body_html: str = Field(default="", max_length=100_000)


@board_router.post("/pages/{slug}/sections", response_model=SectionOut, status_code=status.HTTP_201_CREATED)
def add_section(slug: str, payload: SectionCreate, request: Request, auth: BoardAuth = Depends(can_edit),
                db: Session = Depends(get_db)) -> SectionOut:
    if slug not in PAGES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Page not found.")
    import uuid

    max_order = db.scalar(select(func.coalesce(func.max(PageSection.sort_order), 0)).where(PageSection.page_slug == slug)) or 0
    section = PageSection(
        page_slug=slug, section_key=f"custom-{uuid.uuid4().hex[:12]}", label="Additional section",
        heading=(payload.heading or "").strip() or None, body_html=sanitize_html(payload.body_html),
        sort_order=max_order + 10, is_custom=True, updated_by_id=auth.person.id,
    )
    db.add(section)
    db.flush()
    audit.record(db, actor=auth.person, action="cms.section_added", entity_type="page_section", entity_id=section.id,
                 summary=f"Added a section to {PAGES[slug]}", context=request_context(request))
    db.commit()
    return _section_out(section)


@board_router.delete("/sections/{section_id}", response_model=Message)
def delete_section(section_id: int, request: Request, auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> Message:
    section = db.get(PageSection, section_id)
    if section is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Section not found.")
    if not section.is_custom:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Built-in sections can be hidden but not deleted.")
    audit.record(db, actor=auth.person, action="cms.section_deleted", entity_type="page_section", entity_id=section.id,
                 details={"heading": section.heading}, context=request_context(request))
    db.delete(section)
    db.commit()
    return Message(message="Section deleted.")


class ReorderRequest(APIModel):
    ids: list[int]


@board_router.post("/pages/{slug}/reorder", response_model=Message)
def reorder_sections(slug: str, payload: ReorderRequest, auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> Message:
    sections = {s.id: s for s in db.scalars(select(PageSection).where(PageSection.page_slug == slug))}
    if set(payload.ids) != set(sections):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Include every section of the page exactly once.")
    for index, section_id in enumerate(payload.ids):
        sections[section_id].sort_order = (index + 1) * 10
    audit.record(db, actor=auth.person, action="cms.sections_reordered", entity_type="page", entity_id=slug)
    db.commit()
    return Message(message="Order saved.")


@board_router.post("/media", status_code=status.HTTP_201_CREATED)
async def upload_media(request: Request, file: UploadFile = File(...), auth: BoardAuth = Depends(can_edit),
                       db: Session = Depends(get_db)) -> dict[str, object]:
    """An image for use inside page sections or emails. Served publicly."""
    upload = await uploads.validate_upload(file, uploads.WEB_IMAGE_TYPES, max_bytes=5 * 1024 * 1024, label="Image")
    key = new_key("public/media", upload.extension)
    get_storage().put(key, upload.data, upload.mime_type)
    asset = EmailAsset(kind="image", storage_key=key, original_filename=upload.original_filename, mime_type=upload.mime_type,
                       size_bytes=upload.size_bytes, uploaded_by_id=auth.person.id)
    db.add(asset)
    db.flush()
    audit.record(db, actor=auth.person, action="media.uploaded", entity_type="media", entity_id=asset.id, context=request_context(request))
    db.commit()
    return {"id": asset.id, "url": media_url(asset), "filename": asset.original_filename}


# ---------------------------------------------------------------------------
# Board: settings
# ---------------------------------------------------------------------------


class FooterLink(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=500)


class SiteSettingsUpdate(APIModel):
    site_title: str = Field(min_length=1, max_length=120)
    site_subtitle: str = Field(default="", max_length=200)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=40)
    mailing_address: str | None = Field(default=None, max_length=500)
    physical_address: str | None = Field(default=None, max_length=500)
    map_url: str | None = Field(default=None, max_length=500)
    social_facebook: str | None = Field(default=None, max_length=500)
    social_instagram: str | None = Field(default=None, max_length=500)
    social_youtube: str | None = Field(default=None, max_length=500)
    footer_links: list[FooterLink] = Field(default_factory=list, max_length=12)
    background_check_url: str | None = Field(default=None, max_length=500)


class MembershipSettingsUpdate(APIModel):
    dues_amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    cleanup_discount_amount: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    renewal_cutoff_month: int = Field(ge=1, le=12)
    renewal_cutoff_day: int = Field(ge=1, le=31)
    accepting_waiting_list: bool


class RulesUpdate(APIModel):
    range_rules: list[str] = Field(min_length=1, max_length=60)
    agreement_clause: str = Field(min_length=1, max_length=4000)
    reporting_clause: str = Field(default="", max_length=4000)


def _settings_out(row: SiteSettings) -> dict[str, object]:
    return {
        "site_title": row.site_title, "site_subtitle": row.site_subtitle, "contact_email": row.contact_email,
        "contact_phone": row.contact_phone, "mailing_address": row.mailing_address, "physical_address": row.physical_address,
        "map_url": row.map_url, "social_facebook": row.social_facebook, "social_instagram": row.social_instagram,
        "social_youtube": row.social_youtube, "footer_links": row.footer_links or [],
        "background_check_url": row.background_check_url,
        "dues_amount": str(row.dues_amount), "cleanup_discount_amount": str(row.cleanup_discount_amount),
        "renewal_cutoff_month": row.renewal_cutoff_month, "renewal_cutoff_day": row.renewal_cutoff_day,
        "accepting_waiting_list": row.accepting_waiting_list,
        "rules_version": row.rules_version, "range_rules": row.range_rules,
        "agreement_clause": row.rules_agreement_clause, "reporting_clause": row.rules_reporting_clause,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@board_router.get("/settings")
def get_site_settings(auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> dict[str, object]:
    return _settings_out(membership.site_settings(db))


def _validate_url(label: str, value: str | None, *, https_only: bool = False) -> str | None:
    value = (value or "").strip() or None
    if value and (not is_safe_http_url(value) or (https_only and not value.startswith("https://"))):
        raise membership.WorkflowError(f"{label} must be a full {'https://' if https_only else 'http(s)://'} link.", {label: "Invalid link."})
    return value


@board_router.put("/settings/site")
def update_site_settings(payload: SiteSettingsUpdate, request: Request, auth: BoardAuth = Depends(can_edit),
                         db: Session = Depends(get_db)) -> dict[str, object]:
    row = membership.site_settings(db)
    email = (payload.contact_email or "").strip() or None
    if email and "@" not in email:
        raise membership.WorkflowError("Contact email looks invalid.", {"contact_email": "Invalid email."})
    row.site_title = payload.site_title.strip()
    row.site_subtitle = payload.site_subtitle.strip()
    row.contact_email = email
    row.contact_phone = (payload.contact_phone or "").strip() or None
    row.mailing_address = (payload.mailing_address or "").strip() or None
    row.physical_address = (payload.physical_address or "").strip() or None
    row.map_url = _validate_url("Map link", payload.map_url)
    row.social_facebook = _validate_url("Facebook", payload.social_facebook, https_only=True)
    row.social_instagram = _validate_url("Instagram", payload.social_instagram, https_only=True)
    row.social_youtube = _validate_url("YouTube", payload.social_youtube, https_only=True)
    row.background_check_url = _validate_url("Background check link", payload.background_check_url, https_only=True)
    row.footer_links = [{"label": link.label.strip(), "url": _validate_url(link.label, link.url) or ""} for link in payload.footer_links]
    row.updated_by_id = auth.person.id
    audit.record(db, actor=auth.person, action="settings.site_updated", entity_type="site_settings", entity_id=1,
                 context=request_context(request))
    db.commit()
    return _settings_out(row)


@board_router.put("/settings/membership")
def update_membership_settings(payload: MembershipSettingsUpdate, request: Request, auth: BoardAuth = Depends(can_manage_settings),
                               db: Session = Depends(get_db)) -> dict[str, object]:
    row = membership.site_settings(db)
    try:
        club_today().replace(month=payload.renewal_cutoff_month, day=payload.renewal_cutoff_day)
    except ValueError as exc:
        raise membership.WorkflowError("That renewal cutoff isn't a real calendar date.") from exc
    if payload.cleanup_discount_amount >= payload.dues_amount:
        raise membership.WorkflowError("The cleanup discount must be less than the dues amount.")
    before = {"dues_amount": str(row.dues_amount), "cleanup_discount_amount": str(row.cleanup_discount_amount),
              "cutoff": f"{row.renewal_cutoff_month}/{row.renewal_cutoff_day}"}
    row.dues_amount = payload.dues_amount
    row.cleanup_discount_amount = payload.cleanup_discount_amount
    row.renewal_cutoff_month = payload.renewal_cutoff_month
    row.renewal_cutoff_day = payload.renewal_cutoff_day
    row.accepting_waiting_list = payload.accepting_waiting_list
    row.updated_by_id = auth.person.id
    audit.record(db, actor=auth.person, action="settings.membership_updated", entity_type="site_settings", entity_id=1,
                 details={"before": before, "dues_amount": str(payload.dues_amount),
                          "cleanup_discount_amount": str(payload.cleanup_discount_amount),
                          "cutoff": f"{payload.renewal_cutoff_month}/{payload.renewal_cutoff_day}"},
                 context=request_context(request))
    db.commit()
    return _settings_out(row)


def _next_rules_version(current: str) -> str:
    """Versions are the publish date ("2026-10-02"), with ".2", ".3"... for
    further changes published the same day."""
    today = club_today().isoformat()
    if current == today:
        return f"{today}.2"
    if current.startswith(today + "."):
        return f"{today}.{int(current.rsplit('.', 1)[1]) + 1}"
    return today


@board_router.put("/settings/rules")
def update_rules(payload: RulesUpdate, request: Request, auth: BoardAuth = Depends(can_manage_settings),
                 db: Session = Depends(get_db)) -> dict[str, object]:
    """Publishing new rules creates a new rules version; applications record
    the version they acknowledged."""
    row = membership.site_settings(db)
    rules = [r.strip() for r in payload.range_rules if r.strip()]
    if not rules:
        raise membership.WorkflowError("Add at least one rule.")
    version = _next_rules_version(row.rules_version)
    row.range_rules = rules
    row.rules_agreement_clause = payload.agreement_clause.strip()
    row.rules_reporting_clause = payload.reporting_clause.strip()
    row.rules_version = version
    row.updated_by_id = auth.person.id
    audit.record(db, actor=auth.person, action="settings.rules_published", entity_type="site_settings", entity_id=1,
                 summary=f"Published Range Rules version {version}", context=request_context(request))
    db.commit()
    return _settings_out(row)


# ---------------------------------------------------------------------------
# Board: site images
# ---------------------------------------------------------------------------


@board_router.get("/images")
def list_images(auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    images = {img.key: img for img in db.scalars(select(SiteImage))}
    return [
        {
            "key": key,
            "label": label,
            "url": image_url(images[key]) if key in images else None,
            "alt_text": images[key].alt_text if key in images else None,
            "original_filename": images[key].original_filename if key in images else None,
            "updated_at": images[key].updated_at if key in images else None,
        }
        for key, label in IMAGE_SLOTS.items()
    ]


@board_router.put("/images/{key}")
async def replace_image(key: str, request: Request, file: UploadFile = File(...), alt_text: str = Form(default="", max_length=255),
                        auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> dict[str, object]:
    if key not in IMAGE_SLOTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Unknown image slot.")
    upload = await uploads.validate_upload(file, uploads.WEB_IMAGE_TYPES, max_bytes=8 * 1024 * 1024, label="Image")
    storage_key = new_key(f"public/site-images/{key}", upload.extension)
    get_storage().put(storage_key, upload.data, upload.mime_type)
    image = db.get(SiteImage, key)
    old_key = image.storage_key if image else None
    if image is None:
        image = SiteImage(key=key, storage_key=storage_key, original_filename=upload.original_filename, mime_type=upload.mime_type)
        db.add(image)
    image.storage_key = storage_key
    image.original_filename = upload.original_filename
    image.mime_type = upload.mime_type
    image.alt_text = alt_text.strip() or None
    image.updated_by_id = auth.person.id
    audit.record(db, actor=auth.person, action="cms.image_replaced", entity_type="site_image", entity_id=key,
                 context=request_context(request))
    db.commit()
    delete_quietly(old_key)
    return {"key": key, "url": image_url(image)}


@board_router.delete("/images/{key}", response_model=Message)
def reset_image(key: str, request: Request, auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> Message:
    image = db.get(SiteImage, key)
    if image is not None:
        old_key = image.storage_key
        db.delete(image)
        audit.record(db, actor=auth.person, action="cms.image_reset", entity_type="site_image", entity_id=key,
                     context=request_context(request))
        db.commit()
        delete_quietly(old_key)
    return Message(message="Image reset to the original.")


# ---------------------------------------------------------------------------
# Board: public (downloadable) documents
# ---------------------------------------------------------------------------


@board_router.get("/public-documents", response_model=list[PublicDocumentOut])
def list_public_documents(auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> list[PublicDocumentOut]:
    return [_public_doc_out(d) for d in db.scalars(select(PublicDocument).order_by(PublicDocument.sort_order, PublicDocument.title))]


@board_router.post("/public-documents", response_model=PublicDocumentOut, status_code=status.HTTP_201_CREATED)
async def create_public_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=200),
    description: str = Form(default="", max_length=2000),
    category: str = Form(default="general", max_length=60),
    auth: BoardAuth = Depends(can_edit),
    db: Session = Depends(get_db),
) -> PublicDocumentOut:
    upload = await uploads.validate_upload(file, uploads.PDF_ONLY | uploads.WEB_IMAGE_TYPES, label="Document")
    key = new_key("public/documents", upload.extension)
    get_storage().put(key, upload.data, upload.mime_type)
    document = PublicDocument(
        title=title.strip(), description=description.strip() or None, category=category.strip() or "general",
        storage_key=key, original_filename=upload.original_filename, mime_type=upload.mime_type,
        size_bytes=upload.size_bytes, uploaded_by_id=auth.person.id,
    )
    db.add(document)
    db.flush()
    audit.record(db, actor=auth.person, action="cms.document_published", entity_type="public_document", entity_id=document.id,
                 summary=document.title, context=request_context(request))
    db.commit()
    return _public_doc_out(document)


class PublicDocumentUpdate(APIModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    category: str = Field(default="general", max_length=60)
    is_published: bool = True
    sort_order: int = 0


@board_router.patch("/public-documents/{document_id}", response_model=PublicDocumentOut)
def update_public_document(document_id: int, payload: PublicDocumentUpdate, request: Request, auth: BoardAuth = Depends(can_edit),
                           db: Session = Depends(get_db)) -> PublicDocumentOut:
    document = db.get(PublicDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    document.title = payload.title.strip()
    document.description = (payload.description or "").strip() or None
    document.category = payload.category.strip() or "general"
    document.is_published = payload.is_published
    document.sort_order = payload.sort_order
    audit.record(db, actor=auth.person, action="cms.document_updated", entity_type="public_document", entity_id=document.id,
                 context=request_context(request))
    db.commit()
    return _public_doc_out(document)


@board_router.delete("/public-documents/{document_id}", response_model=Message)
def delete_public_document(document_id: int, request: Request, auth: BoardAuth = Depends(can_edit), db: Session = Depends(get_db)) -> Message:
    document = db.get(PublicDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
    key = document.storage_key
    audit.record(db, actor=auth.person, action="cms.document_deleted", entity_type="public_document", entity_id=document.id,
                 summary=document.title, context=request_context(request))
    db.delete(document)
    db.commit()
    delete_quietly(key)
    return Message(message="Document deleted.")
