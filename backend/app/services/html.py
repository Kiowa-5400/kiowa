"""Server-side HTML sanitization for board-authored rich text.

CMS sections, event descriptions and emails are sanitized on every write,
no matter who wrote them, so stored XSS isn't possible even from an
authenticated (or compromised) board account.
"""

from __future__ import annotations

import html
import re

import nh3

ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "s", "a", "ul", "ol", "li",
    "h2", "h3", "h4", "blockquote", "hr", "img", "span", "div",
    "table", "thead", "tbody", "tr", "th", "td",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target", "class"},
    "img": {"src", "alt", "width", "height", "class"},
    "span": {"class"},
    "div": {"class"},
    "p": {"class"},
    "ol": {"class"},
    "ul": {"class"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
URL_SCHEMES = {"http", "https", "mailto", "tel"}


def sanitize_html(value: str | None) -> str:
    if not value:
        return ""
    cleaned = nh3.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=URL_SCHEMES,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )
    return cleaned.strip()


def html_to_text(value: str) -> str:
    """Plain-text alternative for emails."""
    text = re.sub(r"<(br|/p|/li|/h[2-4]|/tr)\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 (\1)", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_safe_http_url(value: str | None) -> bool:
    return bool(value) and re.match(r"^https?://[^\s<>\"']+$", value or "", re.IGNORECASE) is not None
