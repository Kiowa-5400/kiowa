"""Upload validation: size, extension, declared type and actual file signature.

The browser-supplied Content-Type is never trusted on its own; the leading
bytes must match the format the file claims to be (ported from kiowa-gun's
lib/fileSignature.ts).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePath

from fastapi import HTTPException, UploadFile, status

from app.core.config import get_settings


def _starts(head: bytes, sig: bytes) -> bool:
    return head.startswith(sig)


SIGNATURES = {
    "application/pdf": lambda h: _starts(h, b"%PDF"),
    "image/jpeg": lambda h: _starts(h, b"\xff\xd8\xff"),
    "image/png": lambda h: _starts(h, b"\x89PNG\r\n\x1a\n"),
    "image/gif": lambda h: _starts(h, b"GIF8"),
    "image/webp": lambda h: _starts(h, b"RIFF") and h[8:12] == b"WEBP",
    "image/avif": lambda h: h[4:8] == b"ftyp" and h[8:12] in (b"avif", b"avis"),
    "image/heic": lambda h: h[4:8] == b"ftyp" and h[8:12] in (b"heic", b"heix", b"mif1"),
}

EXTENSIONS = {
    "application/pdf": (".pdf",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/gif": (".gif",),
    "image/webp": (".webp",),
    "image/avif": (".avif",),
    "image/heic": (".heic", ".heif"),
}

# Membership proof can be a photo straight off a phone camera or a scanned PDF.
MEMBERSHIP_DOCUMENT_TYPES = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/heic", "image/avif"}
)
WEB_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"})
PDF_ONLY = frozenset({"application/pdf"})
EMAIL_ATTACHMENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"})


@dataclass(frozen=True)
class ValidatedUpload:
    data: bytes
    mime_type: str
    extension: str
    original_filename: str
    size_bytes: int
    sha256: str


def detect_type(head: bytes) -> str | None:
    for mime, check in SIGNATURES.items():
        if check(head):
            return mime
    return None


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def describe(allowed: frozenset[str]) -> str:
    names = sorted({EXTENSIONS[m][0].lstrip(".").upper() for m in allowed})
    return ", ".join(names[:-1]) + (f" or {names[-1]}" if len(names) > 1 else names[0])


async def validate_upload(
    upload: UploadFile, allowed: frozenset[str], *, max_bytes: int | None = None, label: str = "File"
) -> ValidatedUpload:
    limit = max_bytes or get_settings().max_upload_bytes
    data = await upload.read(limit + 1)
    if not data:
        raise _bad(f"{label} is empty. Please choose a file.")
    if len(data) > limit:
        raise _bad(f"{label} is too large. The limit is {limit // (1024 * 1024)} MB.")

    filename = PurePath(upload.filename or "upload").name[:255] or "upload"
    extension = PurePath(filename).suffix.lower()
    detected = detect_type(data[:16])

    if detected is None or detected not in allowed:
        raise _bad(f"{label} must be a {describe(allowed)} file.")
    # The declared type is advisory, but an explicit mismatch is suspicious.
    declared = (upload.content_type or "").split(";")[0].strip().lower()
    if declared and declared not in {"application/octet-stream", detected} and not (
        declared == "image/jpg" and detected == "image/jpeg"
    ):
        raise _bad(f"{label} doesn't look like a valid {describe(frozenset({detected}))} file.")
    if extension and extension not in EXTENSIONS[detected]:
        raise _bad(f"{label} has the wrong file extension for its contents.")

    return ValidatedUpload(
        data=data,
        mime_type=detected,
        extension=EXTENSIONS[detected][0],
        original_filename=filename,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
