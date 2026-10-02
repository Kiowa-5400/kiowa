"""Board role -> permission mapping. The single place board authorization is decided.

Role hierarchy (ported from kiowa-gun): tech_admin > president = vice_president >
treasurer = board_member. Treasurer is a board member who also sees financials.
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    CONTENT_EDIT = "content.edit"  # pages, images, public documents, settings text
    CALENDAR_MANAGE = "calendar.manage"
    MATCHES_MANAGE = "matches.manage"
    APPLICATIONS_REVIEW = "applications.review"
    MEMBERS_VIEW = "members.view"
    MEMBERS_EDIT = "members.edit"
    MEMBERS_EXPORT = "members.export"
    DOCUMENTS_REVIEW = "documents.review"
    COMMUNICATIONS_SEND = "communications.send"
    PAYMENTS_VIEW = "payments.view"
    PAYMENTS_MANAGE = "payments.manage"  # manual payments, refunds, reconciliation
    SETTINGS_MANAGE = "settings.manage"  # dues amount, renewal cutoff, rules version
    BOARD_MANAGE = "board.manage"
    AUDIT_VIEW = "audit.view"


_EVERY_BOARD_MEMBER = {
    Permission.CONTENT_EDIT,
    Permission.CALENDAR_MANAGE,
    Permission.MATCHES_MANAGE,
    Permission.APPLICATIONS_REVIEW,
    Permission.MEMBERS_VIEW,
    Permission.MEMBERS_EDIT,
    Permission.DOCUMENTS_REVIEW,
    Permission.COMMUNICATIONS_SEND,
}
_FINANCIAL = {Permission.PAYMENTS_VIEW, Permission.PAYMENTS_MANAGE, Permission.MEMBERS_EXPORT}
_LEADERSHIP = _FINANCIAL | {Permission.SETTINGS_MANAGE, Permission.BOARD_MANAGE, Permission.AUDIT_VIEW}

ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "board_member": frozenset(_EVERY_BOARD_MEMBER),
    "treasurer": frozenset(_EVERY_BOARD_MEMBER | _FINANCIAL | {Permission.SETTINGS_MANAGE}),
    "vice_president": frozenset(_EVERY_BOARD_MEMBER | _LEADERSHIP),
    "president": frozenset(_EVERY_BOARD_MEMBER | _LEADERSHIP),
    "tech_admin": frozenset(_EVERY_BOARD_MEMBER | _LEADERSHIP),
}

ROLE_RANK = {"board_member": 0, "treasurer": 0, "vice_president": 1, "president": 1, "tech_admin": 2}

ROLE_LABELS = {
    "tech_admin": "Technology Administrator",
    "president": "President",
    "vice_president": "Vice President",
    "treasurer": "Treasurer",
    "board_member": "Board Member",
}

# Roles the club must always have at least one active holder of.
PROTECTED_ROLES = ("president", "tech_admin")


def permissions_for(role: str) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def has_permission(role: str, permission: Permission) -> bool:
    return permission in permissions_for(role)


def can_manage_role(actor_role: str, target_role: str) -> bool:
    """Whether ``actor_role`` may create/edit/remove a login holding ``target_role``."""
    return ROLE_RANK.get(actor_role, -1) >= ROLE_RANK.get(target_role, 99)
