from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import Application, ApplicationStatus, ApplicationType, Document, Payment, Person

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

app = FastAPI(title="Kiowa Gun Club API")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/api/application/submit")
def submit_application(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    first_name = str(payload.get("first_name", "")).strip()
    last_name = str(payload.get("last_name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone = str(payload.get("phone", "")).strip()
    address = str(payload.get("address", "")).strip()
    city = str(payload.get("city", "")).strip()
    state = str(payload.get("state", "")).strip()
    zip_code = str(payload.get("zip", "")).strip()
    signature = str(payload.get("signature", "")).strip()
    accept_rules = bool(payload.get("accept_rules"))
    application_type = str(payload.get("application_type") or "renew_membership")

    if not all([first_name, last_name, email, phone, address, city, state, zip_code, signature]):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please complete all required personal information fields before submitting.",
        )

    if not accept_rules:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please acknowledge the Kiowa Gun Club Range Rules before submitting.",
        )

    normalized_type = "renewal" if application_type == "renew_membership" else "waiting_list"
    person = db.query(Person).filter(Person.email == email).first()
    if person is None:
        person = Person(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone or None,
            address=address or None,
            city=city or None,
            state=state or None,
            zip_code=zip_code or None,
            status="visitor",
        )
        db.add(person)
        db.flush()
    else:
        person.first_name = first_name
        person.last_name = last_name
        person.phone = phone or person.phone
        person.address = address or person.address
        person.city = city or person.city
        person.state = state or person.state
        person.zip_code = zip_code or person.zip_code

    application = Application(
        person_id=person.id,
        application_type=normalized_type,
        status=ApplicationStatus.SUBMITTED.value,
        amount_due=150.00 if normalized_type == "renewal" else 0.0,
        rules_version="2026-10-01",
        rules_acknowledged=True,
        signature=signature,
        notes=payload.get("membership_notes") or "",
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
                    file_size=0,
                    mime_type="application/octet-stream",
                )
            )

    db.commit()
    db.refresh(application)
    db.refresh(person)

    return {
        "message": f"Thank you, {person.first_name} {person.last_name}. Your application has been received and is pending review.",
        "application": {
            "id": application.id,
            "status": application.status,
            "person": _serialize_person(person),
            "application_type": application.application_type,
        },
    }


@app.get("/api/board/dashboard")
def board_dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
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
def board_applications(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    applications = db.query(Application).order_by(Application.created_at.desc()).all()
    return [_serialize_application(application) for application in applications]


@app.get("/api/people")
def people_index(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    people = db.query(Person).order_by(Person.created_at.desc()).all()
    return [_serialize_person(person) for person in people]
