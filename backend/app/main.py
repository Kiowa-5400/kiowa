from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Kiowa Gun Club API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4173", "http://localhost:5173", "http://localhost:4174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/application/form")
def application_form() -> dict:
    return {
        "application_types": [
            {"value": "renew_membership", "label": "Renew My Membership"},
            {"value": "waiting_list", "label": "Apply for the Waiting List"},
        ],
        "document_requirements": {
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
                    "label": "Background Check Cover Page",
                    "required": True,
                    "description": "Upload the cover page from the criminalwatchdog.com background check report.",
                },
                {
                    "label": "Concealed Carry License",
                    "required": False,
                    "description": "Optional alternative: upload a concealed-carry license from any state.",
                },
            ],
        },
        "rules_text": "Range flag at gate must be raised anytime you are on the property. Range flag at firing line must be raised when shooting on the line or downrange.\n\nAll shooting on rifle ranges MUST be done from the permanent firing line.\n\nI will not shoot when work crews are on the range.\n\nI will follow all of the safety rules and guidelines I have been taught about safe gunhandling. I am responsible for my guest's actions while on property.",
    }


@app.post("/api/application/submit")
def submit_application(payload: dict) -> dict:
    applicant = f"{payload.get('first_name', '').strip()} {payload.get('last_name', '').strip()}".strip()
    status = "Submitted for board review"
    return {
        "message": f"Thank you, {applicant or 'Applicant'}. Your application has been received and is pending review.",
        "application": {"status": status},
    }
