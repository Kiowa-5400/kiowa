from __future__ import annotations


def send_application_notification(email: str, applicant_name: str) -> str:
    return f"Notification queued for {applicant_name} at {email}."
