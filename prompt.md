# Kiowa Gun Club — Production Completion & Feature Migration Prompt

## Mission

You are the implementation agent responsible for taking the current geeko452100/kiowa repository from its simplified prototype state to a complete, production-ready Kiowa Gun Club application.

You have two repositories available as source material:

- TARGET: geeko452100/kiowa
- REFERENCE/SOURCE: geeko452100/kiowa-gun

The repositories have different purposes:

- kiowa-gun is the older, feature-rich implementation. It contains the most complete version of the club's business workflows, CMS behavior, membership workflow, board administration, communications, calendar/match features, and production-oriented edge cases.
- kiowa is the deliberate remake. It simplifies the architecture into:
  - apps/www — public website
  - apps/apply — membership/application experience
  - apps/board — board/admin application
  - backend — Python/FastAPI API
  - PostgreSQL/SQLAlchemy as the intended production data layer

THE GOAL IS NOT TO MERGE THE TWO REPOSITORIES LITERALLY.

The goal is to keep the architecture, simplicity, separation of concerns, and React/FastAPI direction of kiowa, while recovering the valuable functionality and business rules that were already correctly developed in kiowa-gun.

Think of kiowa-gun as the requirements and behavior reference and kiowa as the architecture to finish.

Do not move the old Next.js/D1/Cloudflare architecture into kiowa.

---

# 1. Non-Negotiable Architecture

Keep kiowa as the target architecture unless a change is genuinely necessary.

## Frontend applications

Maintain three independent React/TypeScript/Vite applications:

- apps/www
- apps/apply
- apps/board

They should share the same backend API and database rather than duplicating business logic.

## Backend

Keep:

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL in production
- Alembic or an equivalent real migration system

Do not replace FastAPI with Next.js API routes.

## Production platform

The target deployment environment is Render.

Design the application so that:

- the FastAPI service can run as a Render web service
- PostgreSQL runs as the production database
- each React application can be deployed as a static site or otherwise cleanly served
- environment variables/secrets are used for all credentials
- uploaded private documents are stored in durable private object storage, not Render's ephemeral filesystem

Cloudflare-specific D1/OpenNext/Workers implementation from kiowa-gun must NOT be copied into the target.

---

# 2. First Task: Perform a Feature-by-Feature Audit

Before making major changes, inspect both repositories completely enough to build a migration map.

Create an internal matrix:

| Capability | kiowa-gun behavior | kiowa current state | Target implementation |
|---|---|---|---|
| Authentication | mature admin/member sessions | partial | migrate behavior |
| Board roles | mature roles/permissions | basic board role | implement |
| CMS | editable page sections/settings/images | mostly absent/static | implement |
| Calendar | DB + recurrence + attachments | static/public prototype | implement |
| Matches | discipline + results + photos | static | implement |
| Members | groups/status/portal | partial people model | implement |
| Membership | application/review/payment workflow | partial | implement |
| Documents | uploads/review/storage | local filesystem | production object storage |
| Payments | Stripe workflow | mock checkout | real Stripe |
| Email | campaigns + analytics | absent/minimal | implement |
| SMS | opt-in + campaigns/reminders | absent/minimal | implement |
| Renewal | reminders/termination rules | absent | implement |
| Public pages | CMS-driven | partially hard-coded | API-driven |
| Security | sessions, lockouts, rate limits, filtering | partial | harden |
| Deployment | Cloudflare/D1 | Render/Postgres target | Render production |

Use the existing implementations in kiowa-gun to determine intended behavior wherever the current kiowa implementation is incomplete.

Do not blindly copy old implementation details.

---

# 3. Preserve the Good Parts of kiowa

The simplified kiowa architecture is intentional.

Preserve:

- three React applications
- FastAPI backend
- SQLAlchemy models
- PostgreSQL compatibility
- clear API boundaries
- simple deployment model
- current visual/layout direction
- current Kiowa branding work
- current public navigation
- existing security headers where appropriate
- existing tests where valid
- TypeScript rather than JavaScript
- server-side business rules in FastAPI rather than frontend-only enforcement

Improve the architecture only when required for production correctness.

Avoid introducing:

- unnecessary microservices
- GraphQL
- Next.js
- Cloudflare Workers
- D1
- complicated event infrastructure
- multiple competing authentication systems
- duplicate databases
- duplicated business rules between frontend applications

---

# 4. Migrate the Business Functionality That Is Right in kiowa-gun

The old application contains valuable functionality that must not be lost.

Implement the equivalent behavior in the FastAPI/PostgreSQL architecture.

## 4.1 Board/admin accounts

Implement real board-user management.

The board president must be able to:

- access the board application
- edit club content
- manage members
- review applications
- manage calendar
- manage matches
- manage documents
- manage communications
- manage payment records
- invite/add other board users
- grant appropriate permissions
- deactivate/revoke access

Use a role/permission model.

At minimum support:

- technology/system administrator
- president
- vice president
- treasurer
- board member

Do not rely on a single hard-coded BOARD_EMAIL/BOARD_PASSWORD account for normal operation.

A bootstrap administrator may exist for first deployment, but all normal administration must be database-backed.

Implement:

- secure password hashing
- secure sessions
- session expiration
- logout
- password reset
- account lockout after repeated failed attempts
- constant-time credential verification where appropriate
- audit logging for privileged actions

---

# 5. CMS / Editable Public Website

The board must be able to manage the public website without editing source code.

Implement a simple CMS in apps/board.

Editable content should include:

- home page sections
- about
- contact
- membership
- rules
- calendar introduction/content
- matches introduction/content
- news/announcements if supported
- footer/contact information
- navigation/site title/subtitle
- links
- downloadable documents
- site images

Use database-backed content.

The public apps/www application must retrieve this content through FastAPI.

Do not leave important public content hard-coded in React when it is supposed to be board-editable.

---

# 6. Site Images and Documents

Port the useful image-management behavior from kiowa-gun.

Board users should be able to replace supported site images without modifying code.

Support logical image slots rather than exposing raw implementation details.

Examples:

- logo
- hero image
- rules image
- match/flyer image
- other supported page images

Use durable object storage.

Do NOT store private membership/background-check documents in:

- Git
- the React public assets directory
- Render's local filesystem

Private documents must use private object storage and authenticated access.

Public documents may use controlled public URLs where appropriate.

---

# 7. Calendar

Implement a real database-backed calendar.

The board must be able to:

- create events
- edit events
- delete events
- set title
- date/time
- description
- color/category
- external links
- attachments
- event image
- downloadable document

Implement recurring events.

Port the proven recurrence behavior from kiowa-gun, including the concept of:

- nth weekday of a month
- e.g. second Saturday of each month
- generating individual editable occurrences
- identifying events belonging to the same series
- displaying a human-readable recurrence description

Do not hard-code calendar events in apps/www.

Public calendar data must come from the API.

Make date/time handling explicit and timezone-safe. The club operates in Kansas; avoid browser/server timezone drift.

---

# 8. Matches

Implement database-backed matches.

Matches must support:

- discipline
- date
- time
- notes
- sort order
- PractiScore results URL
- photos/gallery

The public Matches page must group/separate matches by discipline.

Board users must be able to:

- add matches
- edit matches
- delete matches
- change discipline
- add/edit PractiScore results URL
- upload/remove/reorder match photos

A match date should become a link to PractiScore when a results URL exists.

Do not hard-code match dates in React.

---

# 9. Member/Contact Management

Implement the full contact database behavior from kiowa-gun.

The board must be able to:

- view contacts
- search contacts
- filter contacts
- edit contacts
- update status
- update phone/email/address
- maintain board membership flags
- maintain shooting committee membership
- manage renewal information
- manage NRA information
- manage SMS consent
- view application/payment history

Support contact groupings at minimum:

- active members
- board
- shooting committee
- non-members
- waiting list
- former/expired/terminated

A person may belong to multiple logical groups where appropriate.

Do not implement these as mutually exclusive flags if that would lose important business meaning.

---

# 10. Member Portal

Members/approved users should be able to authenticate separately from board administrators.

Implement:

- member login
- logout
- password setup/reset
- email verification
- session management
- account lockout
- profile editing
- phone/email/address editing
- relevant membership information
- NRA information where appropriate
- payment/membership status
- renewal information

A member must only be able to view/edit their own allowed information.

Board users retain appropriate administrative access.

---

# 11. Membership Application Workflow

Port the mature membership workflow from kiowa-gun.

Support at minimum:

## Renewal

A renewal applicant should be able to:

- provide/update personal information
- provide required membership information
- provide NRA proof
- optionally provide cleanup/discount documentation
- acknowledge current rules
- sign electronically
- submit application

## Waiting list/new membership

A waiting-list applicant should be able to:

- provide personal information
- provide required documentation
- provide background-check proof OR qualifying concealed-carry documentation as required by the club's current policy
- acknowledge rules
- sign electronically
- submit

## Board review

The board must be able to:

- view submitted applications
- view applicant information
- securely view documents
- approve/reject/request additional information
- record review notes
- update application status
- update membership status
- clear background-check requirements
- validate NRA documentation
- control when an applicant becomes eligible to pay
- generate/send the appropriate payment request

Do not automatically approve a membership merely because an application was submitted.

---

# 12. Documents

Fix the current kiowa document implementation.

The current prototype stores uploads on the local filesystem and application submission can represent documents merely by filenames. That is not production-ready.

Implement real multipart upload handling.

Every uploaded document should have:

- owner/application/member
- document type
- original filename
- storage key
- MIME type
- size
- upload timestamp
- review status
- reviewer
- review timestamp
- optional notes

Validate:

- file size
- MIME type
- extension
- file signature/magic bytes where practical

Do not trust browser-provided MIME types alone.

Use private object storage.

Serve private documents through authenticated API endpoints or short-lived signed URLs.

Never expose background checks or other private membership documentation through a public URL.

---

# 13. Payment System

Replace the mock payment implementation in kiowa.

The current target implementation must NOT return fake URLs such as:
https://example.com/checkout/...

Implement real Stripe Checkout.

Requirements:

- production Stripe secret configuration
- Stripe Checkout Session creation
- correct amount from server-side application data
- metadata linking Stripe session to application/member
- webhook signature verification
- idempotent webhook processing
- successful payment recording
- failed/cancelled payment handling
- refunds where appropriate
- payment history
- payment reconciliation
- board payment visibility/analytics

Never trust a client-provided payment amount.

Never mark an application paid merely because the browser returned from Stripe.

The webhook is authoritative.

Do not retain test webhook secrets or mock Stripe paths in production code.

Support the actual membership-payment behavior required by the club. If kiowa-gun contains both historical NMI and Stripe logic, use the final Stripe workflow as the target and do not reintroduce NMI unless explicitly required.

---

# 14. Payment Eligibility

Port the useful single-source-of-truth concept from kiowa-gun.

Do not scatter eligibility rules across endpoints.

Create a backend service/function that derives whether a member/application can pay based on current business rules.

Examples include:

- member status
- background check clearance
- NRA status
- application state

Every payment entry point must use the same eligibility logic.

Record the reason when payment is unavailable.

---

# 15. Renewal Cycle

Port the renewal-cycle behavior from kiowa-gun.

Support:

- annual renewal date/cutoff
- renewal reminders
- 45-day reminder
- 15-day reminder
- prevention of duplicate reminders for the same cycle
- annual termination/expiration process
- preservation of historical payment/audit records

Automated jobs must be idempotent.

Do not delete historical financial records just because a member expires.

Use a scheduler compatible with Render.

Document how scheduled jobs are executed in production.

---

# 16. Email

Implement board email functionality.

Board users should be able to:

- select recipient groups
- send to individual members
- compose subject/body
- use HTML content safely
- include links/buttons
- include appropriate images
- attach supported documents
- preview messages
- send

Use a transactional/bulk email provider through a small provider abstraction.

Do not hard-code a vendor throughout business logic.

The implementation must record:

- campaign
- recipients
- provider message ID
- send status
- failures
- delivery where supported
- opens where supported
- clicks where supported
- bounces
- spam complaints where supported

Use provider webhooks to update analytics.

Respect unsubscribe/consent requirements.

---

# 17. SMS

Port the useful SMS functionality from kiowa-gun, but make the provider implementation maintainable.

Requirements:

- explicit SMS opt-in
- opt-in timestamp
- opt-out support
- recipient group selection
- individual sends
- bulk sends
- campaign history
- delivery/failure status where provider supports it
- optional MMS/media support if the chosen provider supports it
- renewal reminder support

Prefer a real SMS provider API over the old carrier email-to-SMS gateway architecture unless there is a compelling reason to retain that gateway behavior.

Keep SMS behind a provider interface so it can be changed without rewriting the application.

Never send automated SMS to someone without recorded consent.

---

# 18. Communication Analytics

The board should have useful communication history.

For email, show where available:

- sent
- delivered
- failed
- bounced
- opened
- clicked
- spam complaint

For SMS, show where available:

- queued
- sent
- delivered
- failed
- undelivered

Do not fabricate analytics that the provider does not supply.

---

# 19. CSV / Mailing Export

Implement board export tools.

Support exporting appropriate contact information for:

- mailing lists
- postal labels
- third-party mailing services

At minimum support CSV.

Only authorized board roles may export personal data.

Record sensitive exports in audit logs.

---

# 20. Public Website

Complete apps/www.

Main public navigation should include:

- Home
- Contact
- Matches
- Calendar
- About
- Membership/application access as appropriate

Retain the existing simplified layout and design direction.

Update colors and styling to remain consistent with the Kiowa visual palette already established.

The following must be API-driven rather than hard-coded:

- calendar events
- matches
- PractiScore links
- match photos
- editable page content
- news/announcements if implemented
- site settings
- editable images

The public site must gracefully handle:

- empty data
- API failure
- loading state
- mobile layout
- inaccessible images/documents
- stale/deleted events

---

# 21. Application Frontend

Fix the existing contract mismatches between apps/apply and FastAPI.

Do not invent new duplicate endpoints if an existing backend endpoint can be made correct.

Ensure:

- form-definition/form metadata endpoint names match
- application submission calls the actual submission endpoint
- multipart document uploads use the real upload endpoint
- authentication state is handled correctly
- validation errors are displayed
- successful submission is persisted
- application ID is retained
- document uploads are associated with the application
- payment starts only when the server says the application is eligible

Do not consider the application complete until a real end-to-end test passes.

---

# 22. Board Frontend

Expand apps/board into the actual board administration application.

Provide a clear dashboard for:

- pending applications
- waiting-list applications
- active members
- expired/terminated members
- upcoming events
- matches
- recent payments
- communications
- document reviews

Provide dedicated screens for:

- Dashboard
- Applications
- Members/Contacts
- Calendar
- Matches
- Documents
- Pages/CMS
- Images
- Email
- SMS
- Payments
- Board Users
- Settings
- Audit Log

Do not overload one huge React component with every workflow.

Keep the UI simple enough for non-technical board members.

---

# 23. API Design

Refactor the FastAPI application into maintainable modules rather than one enormous main.py.

Use a structure similar to:

backend/app/
  main.py
  core/
  db/
  models/
  schemas/
  api/
    auth.py
    people.py
    applications.py
    documents.py
    payments.py
    calendar.py
    matches.py
    cms.py
    communications.py
    board_users.py
    exports.py
  services/
    auth.py
    membership.py
    payments.py
    storage.py
    email.py
    sms.py
    recurrence.py
    renewal.py
  jobs/
  tests/

Exact structure may differ, but responsibilities must remain separated.

Use:

- Pydantic request/response models
- dependency injection
- consistent HTTP status codes
- centralized authorization
- transaction boundaries
- structured logging
- typed service interfaces

Avoid putting all business logic directly inside route functions.

---

# 24. Database

Move fully to PostgreSQL for production.

Do not rely on:

- SQLite files
- Base.metadata.create_all() as the production migration strategy
- committed database files
- implicit schema creation

Create real migrations.

The migration system must represent:

- people/members
- roles
- sessions
- applications
- documents
- payments
- calendar
- recurrence
- matches
- match photos
- pages/content
- site images
- site settings
- email campaigns
- email recipients
- SMS campaigns
- SMS recipients
- renewal tracking
- audit logs

Add appropriate:

- foreign keys
- indexes
- unique constraints
- check constraints where appropriate

Use timezone-aware timestamps.

Use Decimal/Numeric for monetary amounts.

---

# 25. Data Migration / Preservation Strategy

Do not simply delete the existing kiowa model and rebuild everything without considering the existing work.

Where kiowa-gun has mature behavior or seed data that should be preserved:

1. understand its data model
2. map it to the simplified PostgreSQL schema
3. preserve meaningful content/data
4. rewrite implementation in Python/FastAPI/SQLAlchemy

Do not copy D1/SQLite migrations verbatim.

If a direct migration of existing production data is required, create a documented migration/import script.

---

# 26. Security

Production security is mandatory.

Implement:

- secure password hashing
- secure random session IDs
- HttpOnly cookies where cookie sessions are used
- Secure cookies in production
- SameSite policy
- CSRF protection where applicable
- session expiration
- logout invalidation
- password reset tokens
- email verification
- login rate limiting
- lockout/rate limiting
- API rate limiting for public endpoints
- request validation
- upload validation
- authorization on every private endpoint
- object-level authorization
- security headers
- strict CORS
- production CSP without unnecessary unsafe directives
- no secrets in source control
- no production credentials in tests
- audit logging

Use the security lessons and utilities from kiowa-gun where useful, but rewrite them appropriately for FastAPI.

---

# 27. Audit Logging

Add an audit trail for important administrative actions.

Record at minimum:

- actor
- action
- entity/type
- entity ID
- timestamp
- useful metadata
- IP/request information where appropriate and legally reasonable

Audit:

- board-user changes
- application decisions
- document reviews
- member status changes
- payment adjustments/refunds
- CMS changes
- calendar changes
- match changes
- communication sends
- data exports

Do not log passwords, tokens, full payment secrets, or sensitive document contents.

---

# 28. Content Safety / HTML

If board members can edit rich text:

- sanitize HTML on the backend
- allow only a controlled subset of tags/attributes
- prevent stored XSS
- sanitize links
- avoid executing arbitrary scripts

Never trust CMS HTML because it comes from an authenticated board user.

---

# 29. Error Handling and Observability

Production errors must be diagnosable.

Implement:

- structured logs
- request IDs/correlation IDs
- safe API error responses
- useful server-side exception logging
- health endpoint
- readiness/DB health endpoint where appropriate
- external error monitoring if configured
- no stack traces returned to public users

Do not swallow exceptions silently.

---

# 30. Environment Configuration

Create/update environment examples for every service.

Backend should clearly document variables for:

- DATABASE_URL
- secret key/session signing secret if used
- frontend origins
- Stripe keys
- Stripe webhook secret
- object storage credentials
- object storage bucket
- email provider key
- SMS provider credentials
- application/public URL
- admin bootstrap configuration
- scheduler/cron secret
- error monitoring configuration

Frontend apps should only receive public configuration.

Never expose:

- Stripe secret key
- database URL
- storage secret
- email API secret
- SMS API secret

to browser bundles.

---

# 31. Render Production Deployment

Make the repository deployable on Render.

Provide appropriate:

- render.yaml or clearly documented Render configuration
- build commands
- start commands
- environment variable documentation
- database configuration
- migration command
- health check endpoint
- static frontend build instructions

The FastAPI service must start with a production ASGI server such as Gunicorn/Uvicorn configuration appropriate for Render.

Do not use development reload mode in production.

If scheduled jobs are required, provide a Render-compatible mechanism and document it.

---

# 32. CORS and Domains

Production should support the actual deployed domains.

Do not leave permissive development CORS enabled in production.

Support configurable origins for:

- public site
- application site
- board site

Use environment configuration rather than hard-coded localhost-only assumptions.

---

# 33. Testing

Create a serious test suite.

## Backend unit/integration tests

Test:

- registration
- login
- logout
- lockout
- password reset
- role authorization
- application submission
- document upload
- document authorization
- document review
- membership approval
- payment eligibility
- Stripe webhook signature validation
- duplicate webhook handling
- payment recording
- calendar CRUD
- recurring events
- match CRUD
- member filtering
- member profile authorization
- email campaign authorization
- SMS consent
- exports
- audit logging

## End-to-end workflow tests

At minimum test:

### Renewal
Register/login → submit renewal → upload NRA proof → board review → approve → Stripe payment → payment webhook → active membership.

### Waiting list
Register → submit waiting-list application → upload required documentation → board review → clearance → payment eligibility → payment → membership activation.

### Calendar
Board creates event → public calendar displays it.

Board creates recurrence → generated events display correctly.

### Match
Board creates match → public matches page shows discipline/date → results URL appears → photos display.

### Communications
Board selects group → sends email/SMS → campaign history/analytics update.

---

# 34. Frontend Quality

All three React applications must:

- compile with TypeScript
- have no avoidable TypeScript errors
- have no broken imports
- have no dead routes
- have proper loading states
- have proper error states
- have accessible forms
- have keyboard navigation
- have usable focus states
- have labels for inputs
- have responsive mobile layouts

Do not treat "desktop looks good" as sufficient.

---

# 35. Accessibility

Perform a practical accessibility pass.

Check:

- semantic headings
- labels
- form errors
- button names
- keyboard navigation
- contrast
- focus indicators
- alt text
- dialog accessibility
- mobile touch targets
- reduced-motion considerations where applicable

---

# 36. Visual/Design Rule

Do not redesign the application into something unrelated.

The objective is:

kiowa-gun's mature functionality + kiowa's simplified architecture and current design.

Preserve the existing Kiowa visual identity.

The public site should remain straightforward, clean, responsive, and usable by club members.

The board UI should prioritize clarity over visual complexity.

---

# 37. Things Explicitly Not to Copy from kiowa-gun

Do not blindly carry forward:

- Next.js App Router architecture
- Cloudflare Workers
- OpenNext
- D1
- Drizzle-specific database implementation
- Cloudflare-only environment assumptions
- old NMI payment implementation
- carrier email-to-SMS gateway architecture if a proper SMS provider is available
- duplicated/legacy migration complexity
- historical compatibility hacks that are no longer needed
- implementation details that only existed because of Cloudflare limitations

Instead, port the behavior and requirements into FastAPI/PostgreSQL/Render.

---

# 38. Important Existing kiowa Problems to Fix

The current target repository contains several known prototype-level problems. Explicitly resolve them:

1. Application frontend/backend endpoint mismatches.
2. Application document metadata being accepted without actual file upload.
3. Local filesystem document storage.
4. Mock Stripe checkout.
5. Test/mock webhook behavior in production code.
6. Hard-coded calendar content.
7. Hard-coded match content.
8. Missing board CMS.
9. Missing full contact management.
10. Missing board-user invitation/permissions.
11. Missing member portal.
12. Missing full application review workflow.
13. Missing email campaign system.
14. Missing SMS campaign system.
15. Missing communication analytics.
16. Missing renewal automation.
17. Missing audit logging.
18. Missing production migrations.
19. Committed SQLite database files.
20. Insufficient production storage strategy.
21. Incomplete CORS/environment configuration.
22. Incomplete rate limiting.
23. Incomplete automated workflow tests.
24. Incomplete mobile/accessibility QA.

Do not merely document these issues. Fix them.

---

# 39. Repository Hygiene

Before production:

Remove or exclude:

- committed SQLite production databases
- test databases that should not live in the repository
- temporary files
- mock credentials
- test webhook secrets
- fake checkout URLs
- unused legacy code
- dead API routes
- unused dependencies
- duplicated implementations

Update:

- README
- deployment documentation
- environment examples
- migration instructions
- local development instructions
- testing instructions

---

# 40. Production Acceptance Checklist

Do not consider the application finished until every item below is true.

## Public website

- [ ] Home works
- [ ] About works
- [ ] Contact works
- [ ] Calendar works
- [ ] Matches works
- [ ] Membership/application links work
- [ ] public content comes from API where appropriate
- [ ] mobile layout works
- [ ] accessibility pass completed

## Applications

- [ ] renewal application works
- [ ] waiting-list application works
- [ ] rules acknowledgement works
- [ ] signature works
- [ ] required document validation works
- [ ] real file uploads work
- [ ] board review works
- [ ] approval/decline works
- [ ] payment eligibility works

## Members

- [ ] member database works
- [ ] groups/statuses work
- [ ] profile editing works
- [ ] member portal works
- [ ] email verification works
- [ ] password reset works
- [ ] renewal status works

## Board

- [ ] board login works
- [ ] role/permission model works
- [ ] invitation works
- [ ] dashboard works
- [ ] CMS works
- [ ] calendar management works
- [ ] recurrence works
- [ ] match management works
- [ ] image management works
- [ ] document review works
- [ ] contact management works
- [ ] payment reporting works
- [ ] email works
- [ ] SMS works
- [ ] exports work
- [ ] audit log works

## Payments

- [ ] real Stripe checkout
- [ ] server-side pricing
- [ ] webhook signature validation
- [ ] idempotency
- [ ] payment history
- [ ] failed/cancelled/refunded handling
- [ ] membership status updated only from authoritative payment state

## Communications

- [ ] recipient groups
- [ ] email sending
- [ ] email attachments/images/links where supported
- [ ] email analytics
- [ ] SMS opt-in
- [ ] SMS sending
- [ ] SMS analytics where supported
- [ ] renewal reminders
- [ ] campaign history

## Production

- [ ] PostgreSQL
- [ ] migrations
- [ ] durable object storage
- [ ] Render deployment
- [ ] production CORS
- [ ] production secrets
- [ ] health check
- [ ] structured logging
- [ ] rate limiting
- [ ] security headers
- [ ] private document authorization
- [ ] no test secrets
- [ ] no mock payment URLs
- [ ] no committed production DB
- [ ] backup/recovery strategy documented

---

# 41. Implementation Strategy

Work in phases, but do not stop after documenting a phase.

## Phase 1 — Foundation

- audit both repositories
- finalize PostgreSQL schema
- create migrations
- refactor FastAPI structure
- establish auth/session/roles
- establish object storage abstraction
- establish provider abstractions
- establish error handling/logging
- establish tests

## Phase 2 — Membership

- fix application frontend/backend contract
- real document upload
- application review
- member/contact database
- member portal
- membership status rules
- renewal cycle

## Phase 3 — Public CMS

- page content
- site settings
- images
- documents
- API-driven public pages

## Phase 4 — Calendar and Matches

- calendar CRUD
- recurrence
- attachments
- match CRUD
- disciplines
- PractiScore links
- galleries

## Phase 5 — Payments

- Stripe Checkout
- webhooks
- idempotency
- reconciliation
- board reporting

## Phase 6 — Communications

- email
- SMS
- consent
- analytics
- renewal reminders

## Phase 7 — Production

- Render configuration
- migrations
- storage
- secrets
- security
- monitoring
- accessibility
- mobile QA
- end-to-end testing

---

# 42. How to Make Decisions During Implementation

When deciding whether to copy something from kiowa-gun, ask:

### Is it business behavior?
If yes, preserve it unless it conflicts with the current requirements.

### Is it implementation-specific to Next.js/Cloudflare/D1?
If yes, rewrite it for FastAPI/PostgreSQL/Render.

### Is it a workaround for the old architecture?
If yes, do not automatically carry it forward.

### Is it a security or reliability improvement?
Preserve the underlying protection and implement it using the new architecture.

### Is it a feature that makes board administration easier?
Prefer to preserve it.

### Is it unnecessary complexity?
Simplify it.

The target should feel like:

> The same Kiowa Gun Club application, but with a cleaner, easier-to-maintain architecture.

---

# 43. Final Rule

Do not stop when the application merely builds.

Do not stop when the pages render.

Do not stop when the database exists.

Do not stop when individual endpoints work.

The final standard is:

A real board member can operate the club website and membership system without editing code, while members can safely apply, maintain their profiles, upload required documents, pay dues, and receive communications—and the whole system can be deployed and operated reliably on Render with PostgreSQL.

If a feature already works correctly in kiowa-gun, preserve its behavior while simplifying its implementation.

If kiowa-gun and kiowa disagree, prefer:

1. the current documented Kiowa Gun Club business requirement,
2. the mature behavior in kiowa-gun,
3. the simpler architecture of kiowa,
4. production security/reliability,
5. minimal implementation complexity.

Never sacrifice required business functionality merely to keep the new code small.

Never sacrifice the simplified architecture merely because the old application already contains an implementation.

BUILD THE FINISHED PRODUCT IN geeko452100/kiowa.


---

# 44. Visual Design and Color Palette — kiowa-gun is the Reference

The visual palette from kiowa-gun is preferred over the current kiowa palette.

Use kiowa-gun's actual styling as the visual color reference while preserving kiowa's simpler layouts and architecture.

The inspected kiowa-gun stylesheet uses a distinctive palette including:

- deep near-black/charcoal: #0d0f0a
- dark forest/olive green: #17250f, #1c2415, #2c3e1f
- muted sage/green: #4c5e3a
- warm off-white/cream: #f2f0ea
- muted warm neutral: #cbc6b8
- warm brown: #5c3a1e
- brick/red accent: #a8291a
- lighter red/coral states: #b8493c, #ffb4a8, #ff8a80
- warm gold/yellow accent: #ffd166
- pale gold states: #ffd9a3
- light blue accent: #9fd3ff
- pale green states: #9be89b, #8fd694
- very light green background/state: #eafff0

These values are references extracted from kiowa-gun's actual stylesheet, not a request to copy its CSS framework.

## Required visual direction

Use the kiowa-gun palette as the source of truth for primary/secondary backgrounds, cards, navigation, text, buttons, links, borders, focus states, success/warning/error states, badges, calendar categories, match categories, form controls, and dashboard cards.

Create semantic CSS variables/tokens such as:

- --color-bg
- --color-surface
- --color-surface-muted
- --color-text
- --color-text-muted
- --color-primary
- --color-primary-hover
- --color-accent
- --color-success
- --color-warning
- --color-danger
- --color-border
- --color-focus

Do not scatter raw hex values throughout the React applications.

## What to preserve from kiowa

Do NOT copy the old kiowa-gun page structure or styling implementation wholesale.

Keep kiowa's cleaner page layouts, responsive structure, simplified component organization, three-app architecture, and spacing/layout where already good.

Change the visual treatment so that the finished product feels like the kiowa-gun brand.

The intended result is:

**kiowa's architecture and layout + kiowa-gun's functionality + kiowa-gun's color/visual identity.**

## Visual QA requirement

Before production:

1. Compare all three apps against the kiowa-gun visual reference.
2. Verify consistent palette usage across apps/www, apps/apply, and apps/board.
3. Check surfaces, text contrast, buttons, links, form states, alerts, tables, cards, navigation, and mobile views.
4. Do not introduce arbitrary new colors unless necessary for accessibility or a clearly defined semantic state.
5. Preserve sufficient WCAG contrast while adapting the palette.
6. Remove old one-off color values that conflict with the new palette where they are not required by functional state.

The color palette migration is part of the production completion work, not an optional cosmetic task.
