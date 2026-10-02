# Kiowa Gun Club

Website, member portal and board administration for the Kiowa Gun Club (Great Bend, Kansas).

| Part | What it is | Local URL |
|---|---|---|
| `apps/www` | Public website: home, matches, calendar, about, rules, membership, contact | http://localhost:4173 |
| `apps/apply` | Member portal: account, profile, renewals, waiting-list applications, document uploads, dues payment | http://localhost:5173 |
| `apps/board` | Board administration: applications, members, documents, payments, website text & photos, calendar, matches, email, texts, board users, settings, activity log | http://localhost:4174 |
| `backend` | FastAPI API, PostgreSQL (SQLAlchemy + Alembic), scheduled jobs | http://localhost:8000 (`/docs` in development) |
| `apps/shared` | Code shared by the three React apps: design tokens, API client, router, formatting, UI components | — |

All business rules (eligibility, review, payments, renewal cycle, consent) live in the API. The React apps only display what the API returns.

## How it works

**Membership.** A person creates an account (or claims the record the club already has for their email), verifies their email, and fills in one application: renewal or waiting list. The application covers personal info, documents (NRA proof; background check *or* concealed carry license for new members; cleanup-day discount card if claimed) and the Range Rules with a typed signature. The board reviews documents, approves or asks for more information, and emails a payment link. The member pays with Stripe Checkout. The **Stripe webhook** marks the payment paid, makes them a member, and extends their dues to the next renewal cutoff.

**Payment eligibility** is decided in one place (`backend/app/services/membership.py: evaluate_payment_eligibility`) and checked by every payment entry point. The reason payment is blocked is stored on the application and shown to the board.

**Renewal cycle.** Everyone is due by one clubwide cutoff (September 10 by default; editable in Settings). A daily job emails, and texts those who opted in, 45 and 15 days before the cutoff, sends each reminder only once, and terminates unpaid members the day after the cutoff. Contacts and payment history are kept; private documents are deleted.

**Accounts.** One login per person. Board access is a role on top of it (technology administrator, president, vice president, treasurer, board member; see `backend/app/core/permissions.py`). Sessions are HttpOnly cookies with a CSRF header, 8-hour sessions (30 days with "keep me signed in"), and an account lockout after 8 failed attempts.

**Files.** Uploads are checked by size, extension and actual file contents, then stored in a private S3-compatible bucket. Private documents are only served to their owner or the board, and every board view is logged.

## Local development

Requirements: Python 3.12, Node 22.12+, PostgreSQL 16 (or let the tests start an embedded one).

```bash
npm install            # root tooling (concurrently)
npm run install:all    # each app's node_modules + backend/.venv
cp backend/.env.example backend/.env          # then set DATABASE_URL
cp apps/www/.env.example apps/www/.env        # same for apps/apply and apps/board

npm run db:migrate     # create tables and seed the club's content
BOOTSTRAP_ADMIN_EMAIL=you@example.com BOOTSTRAP_ADMIN_NAME="Your Name" BOOTSTRAP_ADMIN_PASSWORD='choose-a-password' \
  backend/.venv/bin/python -m app.cli bootstrap-admin    # run from backend/

npm run dev            # all four servers
```

In development, email and texts go to the API log (`EMAIL_PROVIDER=console`, `SMS_PROVIDER=console`). Verification and reset links appear there. Files are stored under `backend/.storage`. Online payment is disabled unless Stripe test keys are set.

## Tests and checks

```bash
npm run test:backend   # pytest against real PostgreSQL (embedded via pgserver, or TEST_DATABASE_URL)
npm run lint:backend   # ruff
npm run typecheck      # all three apps
npm run build          # typecheck + production build of all three apps
```

The backend suite covers registration, login, logout, lockout, password reset, roles, CSRF, CORS, application submission, uploads and file-signature checks, document authorization and review, approval, eligibility, Stripe webhook signatures/idempotency/refunds/reconciliation, calendar and recurrence, matches and photos, CMS sanitization, contacts and filtering, exports, email/SMS campaigns with analytics webhooks, SMS consent, renewal reminders, termination sweep, and the audit log. It includes end-to-end renewal and waiting-list flows through payment.

## Database changes

Never edit tables by hand or rely on `create_all`. Change `backend/app/models.py`, then:

```bash
cd backend
.venv/bin/alembic revision --autogenerate -m "describe the change"   # review the generated file
.venv/bin/alembic upgrade head
.venv/bin/alembic check                                              # models and migrations agree
```

Render runs `alembic upgrade head` before every deploy.

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Render setup, secrets, Stripe/Resend/Twilio configuration, scheduled jobs, the private-preview switch, backups and recovery. See [docs/MIGRATION.md](docs/MIGRATION.md) for how kiowa-gun's features map to this codebase and how to import its data.
