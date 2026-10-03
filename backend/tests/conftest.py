"""Test fixtures. Tests run against a real PostgreSQL database built by the
Alembic migrations (never ``create_all``).

Set TEST_DATABASE_URL to use an existing server (e.g. in CI); otherwise an
embedded PostgreSQL is started with the ``pgserver`` package.
"""

from __future__ import annotations

import importlib.util
import os
import re
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
_tmp = Path(tempfile.mkdtemp(prefix="kiowa-tests-"))


def _database_url() -> str:
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    import pgserver

    server = pgserver.get_server(str(_tmp / "pg"), cleanup_mode="stop")
    server.psql("CREATE DATABASE kiowa_test;")
    return server.get_uri("kiowa_test")


os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": _database_url(),
        "SECRET_KEY": "test-secret-key-that-is-long-enough-1234567890",
        "CORS_ORIGINS": "http://localhost:5174,http://localhost:5173,http://localhost:4174,http://localhost:4173",
        "STORAGE_BACKEND": "local",
        "LOCAL_STORAGE_DIR": str(_tmp / "storage"),
        "EMAIL_PROVIDER": "console",
        "SMS_PROVIDER": "console",
        "STRIPE_SECRET_KEY": "sk_test_unit_tests_only",
        "STRIPE_WEBHOOK_SECRET": "whsec_unit_tests_only",
        "RESEND_WEBHOOK_SECRET": "whsec_dGVzdC1yZXNlbmQtc2VjcmV0",
        "CRON_SECRET": "cron-test-secret",
        "PORTAL_APP_URL": "http://localhost:5174",
        "APPLY_APP_URL": "http://localhost:5173",
        "BOARD_APP_URL": "http://localhost:4174",
        "API_PUBLIC_URL": "http://testserver",
        "LOG_LEVEL": "WARNING",
    }
)

from alembic.config import Config  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.ratelimit import limiter  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.services import email as email_service  # noqa: E402
from app.services import sms as sms_service  # noqa: E402

_seed_spec = importlib.util.spec_from_file_location("seed", BACKEND / "alembic/versions/0002_seed_club_content.py")
seed_migration = importlib.util.module_from_spec(_seed_spec)  # type: ignore[arg-type]
_seed_spec.loader.exec_module(seed_migration)  # type: ignore[union-attr]


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    """Every test starts from freshly seeded data, empty outboxes and limits."""
    engine = get_engine()
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"))]
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        with Operations.context(MigrationContext.configure(conn)):
            seed_migration.upgrade()
    limiter.reset()
    email_outbox().clear()
    sms_outbox().clear()
    yield


def email_outbox() -> list[email_service.EmailMessage]:
    provider = email_service.get_email_provider()
    assert isinstance(provider, email_service.ConsoleProvider)
    return provider.outbox


def sms_outbox() -> list[tuple[str, str]]:
    provider = sms_service.get_sms_provider()
    assert isinstance(provider, sms_service.ConsoleSmsProvider)
    return provider.outbox


def last_token(to: str, path: str) -> str:
    for message in reversed(email_outbox()):
        if message.to == to and path in message.html:
            match = re.search(re.escape(path) + r"\?token=([A-Za-z0-9_\-]+)", message.html)
            if match:
                return match.group(1)
    raise AssertionError(f"No {path} link emailed to {to}")


@pytest.fixture
def db() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


class Api:
    """A browser-like client: keeps cookies and sends the CSRF header."""

    def __init__(self) -> None:
        self.client = TestClient(app, raise_server_exceptions=False)
        self.csrf: str | None = None

    def request(self, method: str, url: str, **kwargs):  # noqa: ANN003, ANN201
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.csrf and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            headers.setdefault("X-CSRF-Token", self.csrf)
        response = self.client.request(method, url, headers=headers, **kwargs)
        if response.headers.get("content-type", "").startswith("application/json"):
            body = response.json()
            if isinstance(body, dict) and body.get("csrf_token"):
                self.csrf = body["csrf_token"]
        return response

    def get(self, url: str, **kw):  # noqa: ANN003, ANN201
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw):  # noqa: ANN003, ANN201
        return self.request("POST", url, **kw)

    def put(self, url: str, **kw):  # noqa: ANN003, ANN201
        return self.request("PUT", url, **kw)

    def patch(self, url: str, **kw):  # noqa: ANN003, ANN201
        return self.request("PATCH", url, **kw)

    def delete(self, url: str, **kw):  # noqa: ANN003, ANN201
        return self.request("DELETE", url, **kw)


@pytest.fixture
def api() -> Api:
    return Api()


@pytest.fixture
def new_api():  # noqa: ANN201
    return Api
