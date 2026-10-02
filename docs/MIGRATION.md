# kiowa-gun → kiowa: feature map and data import

kiowa-gun (Next.js on Cloudflare Workers with D1, R2, Resend and an email-to-SMS gateway) was the reference for the club's business rules. This repository keeps kiowa's simpler architecture (three React apps, FastAPI, PostgreSQL on Render) and rebuilds those behaviors in it. No Next.js, D1, Workers or Drizzle code was carried over.

## Feature map

| Capability | kiowa-gun | kiowa now |
|---|---|---|
| Board accounts & roles | `admin_users`, PBKDF2, 5 roles, invite/reset links, lockout, last-president guard | `board_users` role on top of one per-person login (Argon2). Same 5 roles and rank rules, invite/reset/unlock/deactivate, last president/tech admin protected, every change audited. `backend/app/core/permissions.py`, `app/api/board_users.py` |
| Member portal | Separate `members` login; signup only for existing Member rows | Same login for everyone; existing contacts claim their record through an emailed link, and new people register to apply. Email verification is required before sign-in. `app/api/auth.py`, `apps/apply` |
| Contacts & groups | status + `on_board` + `on_shooting_committee` flags | Same model plus waiting list / former groups; search, filters, CSV import, history per person. `app/services/people.py`, `apps/board` Members |
| Application workflow | Sign rules, then upload; board toggles background check, which emails an invoice | Draft → submitted → (needs info) → approved → payment requested → completed. Document review drives NRA verification and background check clearance; notes; decline with reason. `app/services/membership.py` |
| Payment eligibility | `recomputeCanPay` → `can_pay` | `evaluate_payment_eligibility` with stored reason, checked by every payment entry point |
| Payments | Embedded Stripe Checkout, webhook + return-page fulfillment | Hosted Stripe Checkout; **only** the webhook or a server-side reconciliation marks it paid; idempotent events, amount check, refunds (full/partial), check/cash entry, reporting. `app/services/payments.py` |
| Renewal cycle | Sept 10 shared cutoff, 45/15-day texts, annual termination with PII scrub | Same cutoff (now board-editable), reminders by email and text (consent required), idempotent per cycle. Termination keeps the contact record and payment history and deletes private documents. `app/services/renewal.py` |
| NRA expiration | Nightly `nra-check` | Same (`nra-check` job) |
| CMS | In-place editable page sections, custom sections, site settings, site images | Board "Website text & photos": same sections (seeded from kiowa-gun content), custom sections, hide/show, sanitized HTML, image slots with alt text, downloadable forms |
| Calendar | D1 events, nth-weekday series, image/PDF/link | Same, stored as UTC instants entered in Kansas time; series can be previewed and deleted (future or all); 5 categories |
| Matches | Discipline, free-text dates, PractiScore link, photo galleries | Real dates and times, discipline grouping, results link, photo upload/reorder/caption |
| Email | Resend batch, inline images, attachments, open/click/bounce via webhook (secret in URL) | Provider interface (Resend). Group + individual recipients, preview, attachments, images, unsubscribe link + one-click header, Svix-verified webhook analytics; spam complaints auto-unsubscribe |
| SMS | Carrier email-to-SMS gateways via Veriphone lookup; no delivery receipts | Provider interface (Twilio). Consent enforced in one function, STOP/START replies recorded, delivery status webhooks, MMS picture, carrier-filter word check kept as a suggestion |
| Exports | Members CSV | Email list, postal labels, full contact CSV; leadership/treasurer only; formula-injection safe; audited |
| Audit log | — | Every privileged action, document view and export |
| Security | Lockout, timing-safe login, Cloudflare rate limiter, magic-byte checks | All kept, plus HttpOnly cookie sessions with CSRF tokens, strict CORS, CSP, HTML sanitization, private object storage, request IDs |

## Revision items carried over from `revision_prompt.md`

The plain-language and "no dead ends" fixes written for kiowa-gun are built into the new apps:
1. **Account setup.** "First time here? Set up your account" sits on the login page. Registering with an email the club already has emails a set-password link.
2. **One progress indicator.** A single "Step X of 4" stepper with no payment stage. The final button is "Sign and submit application", and the status page explains what happens next.
3. **Rules and signature on one page.** "Read and sign the Range Rules" shows every rule, the agreement, and "Type your full name to sign", plus a printable-form link.
4. **One payment page per application.** There is no separate dues page.
5. **Dues status from renewal dates.** The dashboard counts members as paid up or owing based on their renewal date, never on subscription state.
6. **Clearer labels.** "Website text & photos", and the dashboard says "in the menu" rather than "above".
7. **"Needs attention"** at the top of the board dashboard: applications and documents waiting for review.
8. **Simpler members table.** Name, email, status, paid-through, and a Details toggle; "Approvals" with "Ready to pay dues" / "Waiting on approval".
9. **CSV import** by choosing a file.
10. **Matches:** the date is plain text, with a separate "View results" link.
11. **NRA expiration** is a single date field.
12. **Spelled-out labels:** "National Rifle Association (NRA)", "Background check cover page, or a concealed carry license from any state", "range cleanup-day discount card".
13. **"Member login"** in the public navigation. "Board login" is a quiet footer link.
14. **README** describes the actual screens.

## Questions for the club

- **NRA proof for waiting-list applicants.** kiowa-gun required NRA proof from *every* applicant, and this build does the same. The original spec suggested NRA proof only for renewing members (waiting-list applicants provide the background check or CCL). Please confirm which rule is intended. The rule lives in `document_requirements()` in `backend/app/services/membership.py`.
- **Cleanup-day discount amount.** It starts at $0 (Settings → Dues and renewal) because the amount wasn't recorded in either codebase.
- **Termination.** kiowa-gun scrubbed names and emails of terminated members. This build keeps their contact details so they appear under "Former / expired / terminated" (as the requirements ask) and deletes only their uploaded documents. Confirm this matches the club's privacy expectations.

## Importing kiowa-gun's data

`backend/scripts/import_kiowa_gun.py` imports a D1 export: members, board logins and roles, payment history, matches, calendar events, uploaded files (given a local copy of the R2 bucket), and optionally page text. Usage is in the script's docstring. It is safe to run more than once; people are matched by email. It does **not** import passwords (incompatible hash format), so after the import, tell members to use "Set up your account" with their existing email. Run it with `--dry-run` first.
