from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints


def _phone(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("Enter a 10-digit phone number.")
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def _nra_number(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    if not re.fullmatch(r"\d{5,12}", value):
        raise ValueError("NRA number must be 5 to 12 digits.")
    return value


def _state(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip().upper()[:40]


def _zip(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    if not re.fullmatch(r"\d{5}(-\d{4})?", value.strip()):
        raise ValueError("Enter a 5-digit ZIP code.")
    return value.strip()


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
OptionalText = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=255)]
Phone = Annotated[str | None, AfterValidator(_phone)]
NraNumber = Annotated[str | None, AfterValidator(_nra_number)]
State = Annotated[str | None, AfterValidator(_state)]
Zip = Annotated[str | None, AfterValidator(_zip)]
Email = Annotated[EmailStr, AfterValidator(lambda v: v.strip().lower())]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ProfileUpdate(APIModel):
    first_name: Name | None = None
    last_name: Name | None = None
    phone: Phone = None
    address_line1: OptionalText = None
    address_line2: OptionalText = None
    city: OptionalText = None
    state: State = None
    zip_code: Zip = None
    nra_number: NraNumber = None
    nra_expiration_date: date | None = None
    sms_opt_in: bool | None = None


class Message(BaseModel):
    message: str


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int = Field(ge=1)
    page_size: int
