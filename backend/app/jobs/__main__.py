"""CLI entry point for scheduled jobs: ``python -m app.jobs daily`` or ``python -m app.jobs <job-name>``."""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.jobs import DAILY, JOBS, run_job


def main(argv: list[str]) -> int:
    configure_logging(get_settings().log_level)
    if len(argv) != 2 or (argv[1] != "daily" and argv[1] not in JOBS):
        print(f"usage: python -m app.jobs daily|{'|'.join(JOBS)}", file=sys.stderr)
        return 2
    names = DAILY if argv[1] == "daily" else [argv[1]]
    failed = False
    for name in names:
        with get_sessionmaker()() as db:
            try:
                run_job(db, name)
            except Exception:  # noqa: BLE001 - keep running the remaining jobs; failure is logged and reflected in the exit code
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
