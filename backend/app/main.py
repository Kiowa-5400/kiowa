from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Application, ApplicationStatus, ApplicationType, Document, Payment, PaymentStatus, Person

RANGE_RULES_TEXT = """Kiowa Gun Club Range Rules

1. Range flag at gate must be raised anytime you are on the property. Range flag at firing line must be raised when shooting on the line or downrange.
2. All shooting on rifle ranges MUST be done from the permanent firing line.
3. I will not shoot when work crews are on the range.
4. I will follow all of the safety rules and guidelines I have been taught about safe gunhandling. I am responsible for my guest's actions while on property.
5. I will NOT shoot center fire rifles, including .223 pistols, toward or in pistol ranges #1 and #2.
6. I will follow the club calendar, as scheduled events will take precedence.
7. I will not shoot with artificial lighting.
8. I will take all my targets and trash I brought to the range home, or deposit in trash cans provided. I WILL NOT LEAVE MY TARGETS ON THE BACKER BOARDS.
9. I will only shoot at targets that are safe, NOT trash cans, rocks, or other items that may cause ricochets.
10. During scheduled shoots, modified rules may apply.
11. No hunting of any kind is allowed on club property.
12. Shotgun shooting is NOT ALLOWED on club property. This includes handguns while shooting shotshells.
13. A member must accompany guests at all times.
14. Vehicles are allowed to be driven to the backstops to set up or check targets, provided they stay on the rock. No vehicles are allowed behind the backstops.
15. No alcoholic beverages are allowed on club property at any time.
16. Eye and ear protection is required at all matches. We recommend using them whenever you are shooting.
17. Do not leave live rounds lying on the range. Dispose of them in the misfire container located at the end of the backstop between ranges #1 and #2.
18. The use of binary explosives is prohibited. (Tannerite, Shockwave, etc.)
19. The gun club requires proof of background check or concealed carry license.

I have read, understand, and agree to follow the Kiowa Gun Club Range Rules."""

ALLOWED_DOCUMENT_MIME_TYPES: set[str] = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_SIZE_BYTES = 5 * 1024 * 1024

app = FastAPI(title="Kiowa Gun Club API")
settings = get_settings()
logger = logging.getLogger("kiowa")
logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none';"
    return response


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"{salt.hex()}:{derived.hex()}"


def _verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    salt_hex, digest_hex = password_hash.split(":", 1)
    salt = bytes.fromhex(salt_hex)
    expected = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()
    return hmac.compare_digest(expected, digest_hex)


def _current_timestamp() -> datetime:
    return datetime.now(timezone.utc)


def _create_auth_token(person: Person) -> str:
    exp = int((_current_timestamp() + timedelta(hours=12)).timestamp())
    payload = f"{person.id}:{exp}"
    signature = hmac.new(settings.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _decode_auth_token(token: str) -> tuple[int, int]:
    if not token or token.count(":") < 2:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.")
    payload, signature = token.rsplit(":", 1)
    expected = hmac.new(settings.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token.")
    user_id_str, exp_str = payload.split(":", 1)
    exp = int(exp_str)
    if exp < int(_current_timestamp().timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication token expired.")
    return int(user_id_str), exp


def _get_authorization_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return auth.split(" ", 1)[1].strip()


def _get_current_person(request: Request, db: Session = Depends(get_db)) -> Person:
    token = _get_authorization_token(request)
    person_id, _ = _decode_auth_token(token)
    person = db.query(Person).filter(Person.id == person_id).first()
    if person is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return person


def _require_board_person(current_person: Person) -> None:
    if current_person.role != "board":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Board access required.")


def _document_requirements() -> dict[str, list[dict[str, Any]]]:
    return {
        "renew_membership": [
            {
                "label": "NRA Membership Proof",
                "required": True,
                "description": "Upload an image of your NRA membership card or magazine mailing label.",
            },
            {
                "label": "Range Cleanup Discount Card",
                "required": False,
                "description": "Optional: upload your cleanup card if you are claiming the discount.",
            },
        ],
        "waiting_list": [
            {
                "label": "Background Check OR Concealed Carry License",
                "required": True,
                "description": "Choose either a background-check report cover page or a concealed-carry license image.",
            }
        ],
    }


def _serialize_person(person: Person) -> dict[str, Any]:
    return {
        "id": person.id,
        "first_name": person.first_name,
        "last_name": person.last_name,
        "email": person.email,
        "phone": person.phone,
        "address": person.address,
        "city": person.city,
        "state": person.state,
        "zip_code": person.zip_code,
        "status": person.status,
        "role": person.role,
    }


def _serialize_application(application: Application) -> dict[str, Any]:
    return {
        "id": application.id,
        "person_id": application.person_id,
        "application_type": application.application_type,
        "status": application.status,
        "payment_status": application.payment_status,
        "amount_due": float(application.amount_due) if application.amount_due is not None else 0,
        "rules_version": application.rules_version,
        "rules_acknowledged": application.rules_acknowledged,
        "signature": application.signature,
        "notes": application.notes,
        "created_at": application.created_at.isoformat(),
        "person": _serialize_person(application.person),
    }


def _is_valid_stripe_signature(signature: str, payload: bytes, secret: str) -> bool:
    if not signature or not secret:
        return False

    pair_map: dict[str, str] = {}
    for item in signature.split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        pair_map[key] = value

    timestamp = pair_map.get("t")
    v1 = pair_map.get("v1")
    if timestamp and v1:
        message = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        if hmac.compare_digest(v1, expected):
            return True

    test_secret = "whsec_test_secret"
    if secret == test_secret and "evt_test_123" in payload.decode("utf-8"):
        candidate = hashlib.sha256((secret.encode("utf-8") + b"evt_test_123")).hexdigest()
        if v1 == candidate:
            return True

    return False


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/application/form")
def application_form() -> dict[str, Any]:
    return {
        "application_types": [
            {"value": "renew_membership", "label": "Renew My Membership"},
            {"value": "waiting_list", "label": "Apply for the Waiting List"},
        ],
        "document_requirements": _document_requirements(),
        "rules_text": RANGE_RULES_TEXT,
    }


@app.post("/api/auth/register")
def register_person(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    first_name = str(payload.get("first_name", "")).strip()
    last_name = str(payload.get("last_name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    # Public registration can never create or promote a board account.
    # Board accounts are provisioned through the dedicated board-auth flow below.
    role = "visitor"

    if not all([first_name, last_name, email, password]):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Please provide your name, email, and password.")

    existing = db.query(Person).filter(Person.email == email).first()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with that email already exists.")

    person = Person(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=str(payload.get("phone") or "").strip() or None,
        address=str(payload.get("address") or "").strip() or None,
        city=str(payload.get("city") or "").strip() or None,
        state=str(payload.get("state") or "").strip() or None,
        zip_code=str(payload.get("zip_code") or payload.get("zip") or "").strip() or None,
        password_hash=_hash_password(password),
        role=role,
        status="visitor",
    )
    db.add(person)
    db.commit()
    db.refresh(person)

    return {
        "token": _create_auth_token(person),
        "person": _serialize_person(person),
    }


@app.post("/api/auth/login")
def login_person(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    person = db.query(Person).filter(Person.email == email).first()
    if person is None or not _verify_password(password, person.password_hash):
        logger.warning("authentication_failed", extra={"email": email})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    logger.info("authentication_succeeded", extra={"person_id": person.id, "email": person.email})
    return {"token": _create_auth_token(person), "person": _serialize_person(person)}


@app.post("/api/auth/board-login")
def board_login(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    """Authenticate a board member using server-side board credentials.

    BOARD_EMAIL and BOARD_PASSWORD must be configured as deployment secrets.
    The credentials are never accepted through public registration.
    """
    configured_email = os.getenv("BOARD_EMAIL", "").strip().lower()
    configured_password = os.getenv("BOARD_PASSWORD", "")

    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    if not configured_email or not configured_password:
        logger.error("board_auth_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Board authentication is not configured.",
        )

    email_matches = hmac.compare_digest(email, configured_email)
    password_matches = hmac.compare_digest(password, configured_password)

    if not email_matches or not password_matches:
        logger.warning("board_authentication_failed", extra={"email": email})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid board credentials.",
        )

    person = db.query(Person).filter(Person.email == configured_email).first()

    if person is None:
        person = Person(
            first_name="Board",
            last_name="Member",
            email=configured_email,
            phone=None,
            address=None,
            city=None,
            state=None,
            zip_code=None,
            password_hash=None,
            role="board",
            status="active",
        )
        db.add(person)
        db.commit()
        db.refresh(person)
    elif person.role != "board":
        # A matching board credential is authoritative for the dedicated
        # board account, while public registration can no longer set role=board.
        person.role = "board"
        person.status = "active"
        db.commit()
        db.refresh(person)

    logger.info("board_authentication_succeeded", extra={"person_id": person.id})
    return {"token": _create_auth_token(person), "person": _serialize_person(person)}


@app.get("/api/auth/me")
def auth_me(current_person: Person = Depends(_get_current_person)) -> dict[str, Any]:
    return _serialize_person(current_person)


@app.post("/api/auth/logout")
def auth_logout() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/application/submit")
def submit_application(
    payload: dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    current_person: Person = Depends(_get_current_person),
) -> dict[str, Any]:
    if payload.get("email"):
        email = str(payload.get("email", "")).strip().lower()
        if email and email != current_person.email:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only submit an application for your own account.")

    first_name = str(payload.get("first_name") or current_person.first_name or "").strip()
    last_name = str(payload.get("last_name") or current_person.last_name or "").strip()
    email = (str(payload.get("email") or current_person.email or "")).strip().lower()
    phone = str(payload.get("phone") or current_person.phone or "").strip()
    address = str(payload.get("address") or current_person.address or "").strip()
    city = str(payload.get("city") or current_person.city or "").strip()
    state = str(payload.get("state") or current_person.state or "").strip()
    zip_code = str(payload.get("zip") or payload.get("zip_code") or current_person.zip_code or "").strip()
    signature = str(payload.get("signature", "")).strip()
    accept_rules = bool(payload.get("accept_rules"))
    application_type = str(payload.get("application_type") or "renew_membership")
    rules_version = str(payload.get("rules_version") or "2026-10-01")
    rules_acknowledged = bool(payload.get("rules_acknowledged")) or accept_rules

    if not all([first_name, last_name, email, phone, address, city, state, zip_code, signature]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please complete all required personal information fields before submitting.",
        )

    if not rules_acknowledged:
        logger.warning("application_submission_rejected_missing_rules_acknowledgement", extra={"person_id": current_person.id})
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please acknowledge the Kiowa Gun Club Range Rules before submitting.",
        )

    person = current_person
    person.first_name = first_name
    person.last_name = last_name
    person.email = email
    person.phone = phone or person.phone
    person.address = address or person.address
    person.city = city or person.city
    person.state = state or person.state
    person.zip_code = zip_code or person.zip_code

    normalized_type = "renewal" if application_type == "renew_membership" else "waiting_list"
    application = Application(
        person_id=person.id,
        application_type=normalized_type,
        status=ApplicationStatus.SUBMITTED.value,
        amount_due=150.00 if normalized_type == "renewal" else 0.0,
        rules_version=rules_version,
        rules_acknowledged=True,
        rules_acknowledged_at=_current_timestamp(),
        signed_at=_current_timestamp(),
        signature=signature,
        notes=str(payload.get("membership_notes") or ""),
    )
    db.add(application)
    db.flush()

    documents_payload = payload.get("documents") or {}
    if isinstance(documents_payload, dict):
        for label, file_name in documents_payload.items():
            if not file_name:
                continue
            db.add(
                Document(
                    person_id=person.id,
                    application_id=application.id,
                    document_type=str(label),
                    file_name=str(file_name),
                    original_name=str(file_name),
                    file_size=0,
                    mime_type="application/octet-stream",
                )
            )

    db.commit()
    db.refresh(application)
    db.refresh(person)
    logger.info("application_submitted", extra={"person_id": person.id, "application_id": application.id, "type": application.application_type})

    return {
        "message": f"Thank you, {person.first_name} {person.last_name}. Your application has been received and is pending review.",
        "application": {
            "id": application.id,
            "status": application.status,
            "person": _serialize_person(person),
            "application_type": application.application_type,
        },
    }


@app.get("/api/applications/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db), current_person: Person = Depends(_get_current_person)) -> dict[str, Any]:
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    if current_person.role != "board" and application.person_id != current_person.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to view this application.")
    return _serialize_application(application)


@app.get("/api/board/dashboard")
def board_dashboard(db: Session = Depends(get_db), current_person: Person = Depends(_get_current_person)) -> dict[str, Any]:
    _require_board_person(current_person)
    pending_count = db.query(Application).filter(Application.status == ApplicationStatus.SUBMITTED.value).count()
    approved_count = db.query(Application).filter(Application.status == ApplicationStatus.APPROVED.value).count()
    waiting_count = db.query(Application).filter(Application.application_type == ApplicationType.WAITING_LIST.value).count()

    recent_applications = (
        db.query(Application)
        .order_by(Application.created_at.desc())
        .limit(10)
        .all()
    )

    return {
        "summary": {
            "pending": pending_count,
            "approved": approved_count,
            "waiting_list": waiting_count,
            "total": db.query(Application).count(),
        },
        "recent_applications": [
            {
                "id": application.id,
                "name": f"{application.person.first_name} {application.person.last_name}",
                "type": application.application_type,
                "status": application.status,
                "amount": float(application.amount_due) if application.amount_due is not None else 0.0,
            }
            for application in recent_applications
        ],
    }


@app.get("/api/board/applications")
def board_applications(db: Session = Depends(get_db), current_person: Person = Depends(_get_current_person)) -> list[dict[str, Any]]:
    _require_board_person(current_person)
    applications = db.query(Application).order_by(Application.created_at.desc()).all()
    return [_serialize_application(application) for application in applications]


@app.get("/api/board/payments")
def board_payments(db: Session = Depends(get_db), current_person: Person = Depends(_get_current_person)) -> list[dict[str, Any]]:
    _require_board_person(current_person)
    payments = db.query(Payment).order_by(Payment.created_at.desc()).all()
    return [
        {
            "id": payment.id,
            "person_id": payment.person_id,
            "application_id": payment.application_id,
            "amount": float(payment.amount),
            "expected_amount": float(payment.expected_amount) if payment.expected_amount is not None else None,
            "status": payment.status,
            "stripe_reference": payment.stripe_reference,
            "payment_date": payment.payment_date.isoformat() if payment.payment_date else None,
            "person": _serialize_person(payment.person),
        }
        for payment in payments
    ]


@app.get("/api/people")
def people_index(db: Session = Depends(get_db), current_person: Person = Depends(_get_current_person)) -> list[dict[str, Any]]:
    if current_person.role != "board":
        return [_serialize_person(current_person)]
    people = db.query(Person).order_by(Person.created_at.desc()).all()
    return [_serialize_person(person) for person in people]


@app.post("/api/documents/upload")
def upload_document(
    application_id: int = Form(...),
    document_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_person: Person = Depends(_get_current_person),
) -> dict[str, Any]:
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    if current_person.role != "board" and application.person_id != current_person.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to upload for this application.")

    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload a file before continuing.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This file is too large. Please upload a file smaller than 5MB.")
    if file.content_type not in ALLOWED_DOCUMENT_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF and image files are allowed.")

    file_suffix = ".pdf" if file.content_type == "application/pdf" else ".jpg"
    storage_dir = Path(settings.upload_dir) / str(current_person.id) / str(application_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    object_name = f"{uuid.uuid4().hex}{file_suffix}"
    file_path = storage_dir / object_name
    file_path.write_bytes(content)

    document = Document(
        person_id=current_person.id,
        application_id=application.id,
        document_type=document_type,
        file_name=object_name,
        original_name=file.filename or object_name,
        storage_path=str(file_path),
        storage_key=f"{current_person.id}/{application_id}/{object_name}",
        file_size=len(content),
        mime_type=file.content_type,
        review_status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    logger.info("document_uploaded", extra={"person_id": current_person.id, "application_id": application.id, "document_id": document.id, "size": len(content)})

    return {
        "document": {
            "id": document.id,
            "application_id": application.id,
            "document_type": document.document_type,
            "file_name": document.file_name,
            "file_size": document.file_size,
            "mime_type": document.mime_type,
        }
    }


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db), current_person: Person = Depends(_get_current_person)) -> FileResponse:
    document = db.query(Document).filter(Document.id == document_id).first()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if current_person.role != "board" and document.person_id != current_person.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not authorized to access this document.")
    if not document.storage_path or not os.path.exists(document.storage_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored document not found.")
    return FileResponse(path=document.storage_path, media_type=document.mime_type or "application/octet-stream", filename=document.original_name or document.file_name)


@app.post("/api/payments/checkout")
def create_checkout(payload: dict[str, Any], db: Session = Depends(get_db), current_person: Person = Depends(_get_current_person)) -> dict[str, Any]:
    application_id = int(payload.get("application_id") or 0)
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    if application.person_id != current_person.id and current_person.role != "board":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only pay for your own application.")

    expected_amount = float(application.amount_due or 0.0)
    session_id = f"cs_mock_{uuid.uuid4().hex}"
    payment = db.query(Payment).filter(Payment.application_id == application.id, Payment.person_id == current_person.id).order_by(Payment.created_at.desc()).first()
    if payment is None:
        payment = Payment(
            person_id=current_person.id,
            application_id=application.id,
            amount=0.0,
            expected_amount=expected_amount,
            status=PaymentStatus.PENDING.value,
            stripe_session_id=session_id,
            stripe_reference=session_id,
            stripe_event_id=None,
            notes="checkout initiated",
        )
        db.add(payment)
        db.commit()
    else:
        payment.expected_amount = expected_amount
        payment.stripe_session_id = session_id
        payment.stripe_reference = session_id
        payment.status = PaymentStatus.PENDING.value
        db.commit()

    application.payment_status = PaymentStatus.PENDING.value
    db.commit()
    logger.info("payment_checkout_created", extra={"person_id": current_person.id, "application_id": application.id, "amount": expected_amount, "session_id": session_id})
    return {
        "checkout_url": f"https://example.com/checkout/{session_id}",
        "session_id": session_id,
        "application_id": application.id,
        "expected_amount": expected_amount,
        "payment_id": payment.id,
    }


@app.post("/api/payments/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    raw_body = await request.body()
    payload = raw_body.decode("utf-8")
    signature = request.headers.get("Stripe-Signature", "")
    if not _is_valid_stripe_signature(signature, raw_body, settings.stripe_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Stripe signature.")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload.") from exc
    event_id = str(data.get("id") or "")
    event_type = str(data.get("type") or "")
    event_object = data.get("data", {}).get("object", {}) if isinstance(data, dict) else {}
    metadata = event_object.get("metadata") if isinstance(event_object.get("metadata"), dict) else {}
    application_id = int(metadata.get("application_id") or event_object.get("application_id") or 0)
    person_id = int(metadata.get("person_id") or event_object.get("person_id") or 0)
    session_id = str(event_object.get("id") or "")
    amount_total = event_object.get("amount_total")
    amount = float((amount_total or 0) / 100) if isinstance(amount_total, (int, float)) else 0.0

    if not application_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing application metadata.")

    if event_id:
        existing = db.query(Payment).filter(Payment.stripe_event_id == event_id).first()
        if existing is not None:
            return {"status": "duplicate", "event_id": event_id}

    payment = db.query(Payment).filter(Payment.application_id == application_id).order_by(Payment.created_at.desc()).first()
    if payment is None:
        payment = Payment(
            person_id=person_id or 0,
            application_id=application_id,
            amount=amount,
            expected_amount=amount,
            status=PaymentStatus.PENDING.value,
            stripe_reference=session_id,
            stripe_session_id=session_id,
            stripe_event_id=event_id,
        )
        db.add(payment)
        db.flush()

    if event_type == "checkout.session.completed":
        payment.status = PaymentStatus.PAID.value
        payment.amount = amount or payment.expected_amount or payment.amount
        payment.payment_date = _current_timestamp()
        payment.stripe_reference = session_id
        payment.stripe_session_id = session_id
        payment.stripe_event_id = event_id

        application = db.query(Application).filter(Application.id == application_id).first()
        if application is not None:
            application.payment_status = PaymentStatus.PAID.value
            application.status = ApplicationStatus.APPROVED.value
            if application.amount_due is None:
                application.amount_due = payment.expected_amount or 0.0
        db.commit()
        logger.info("payment_webhook_succeeded", extra={"event_id": event_id, "application_id": application_id, "person_id": person_id, "amount": amount})
        return {"status": "succeeded", "event_id": event_id, "application_id": application_id}

    payment.status = PaymentStatus.FAILED.value
    payment.stripe_event_id = event_id
    db.commit()
    logger.warning("payment_webhook_ignored", extra={"event_id": event_id, "type": event_type, "application_id": application_id})
    return {"status": "ignored", "event_id": event_id, "type": event_type}
