# Deploying

The API, daily jobs and the four React apps (as static sites, see [Static sites](#4-static-sites) below) run on Render, described in [`render.yaml`](../render.yaml) (a Render Blueprint). The PostgreSQL database is on Neon; the API and the daily jobs reach it through `DATABASE_URL`.

| Service | Type | What runs |
|---|---|---|
| `kiowa` | Web service (Python) | `uvicorn app.main:app` with 1 worker and a 10 GB persistent disk; health check `/health`; pre-deploy `alembic upgrade head && python -m app.cli bootstrap-admin` |
| `kiowa-daily-jobs` | Cron job | `python -m app.jobs daily` at 13:00 UTC (8 AM CDT / 7 AM CST) |
| `www`, `portal`, `apply`, `board` | Static sites | The four React apps, built with Vite |

## 1. Before the first deploy

1. **Domains.** The API sets its session cookies itself, so the five sites must share one parent domain: `kiowagunclub.org` (www), `portal.kiowagunclub.org` (member sign-in and account), `apply.kiowagunclub.org` (application form), `board.kiowagunclub.org`, `app.kiowagunclub.org`.
2. **Render storage.** The production API uses the paid Render persistent disk mounted at `/var/data/kiowa-storage`. Keep the API at one instance; the disk is attached to that instance.
3. **Stripe.** In the Stripe Dashboard, add `https://app.kiowagunclub.org/api/webhooks/stripe` for the configured checkout events and copy the signing secret/API key.
4. **Email (Resend).** Verify `kiowagunclub.org` as a sending domain in Resend, create an API key, and add a webhook to `https://app.kiowagunclub.org/api/webhooks/email/resend` for delivered, opened, clicked, bounced and complained events. Copy its signing secret.
5. **Texts (httpSMS now, Twilio later).** Texts are currently sent by the httpSMS app on the club's Android phone (`SMS_PROVIDER=httpsms`); the setup is under **httpSMS** below. Twilio is ready to take over once its toll-free verification is approved: then set `SMS_PROVIDER=twilio` and `SMS_FALLBACK_PROVIDER=httpsms`, and pass the three `TWILIO_*` variables to `kiowa-daily-jobs` in render.yaml.

   **Twilio (toll-free).** In the Twilio Console, buy a toll-free number, create a Messaging Service and add the number to it, then submit toll-free verification for the number. Use https://www.kiowagunclub.org as the website and https://www.kiowagunclub.org/terms and https://www.kiowagunclub.org/privacy as the terms and privacy policy links. Choose web form opt-in: the unchecked, optional text message checkbox on the membership application and member profile (its exact wording is quoted on the terms page). Because those forms are behind sign-in, upload a screenshot of the checkbox as the opt-in proof. Describe the use case as club announcements, event and match schedules and dues renewal reminders for members, and give sample messages that read like the club's real texts; avoid firearm wording, which carriers filter (the board's text composer flags it). In the Messaging Service's Integration settings, set the incoming message webhook to `https://app.kiowagunclub.org/api/webhooks/sms/twilio/inbound` (HTTP POST) so STOP/START replies update each person's consent; delivery status callbacks go to `/api/webhooks/sms/twilio` automatically. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_MESSAGING_SERVICE_SID` on the `kiowa` service. Unverified toll-free numbers are blocked from sending, so texts start working once verification is approved.

   **httpSMS.** As the main provider it sends every text. As the backup, `SMS_FALLBACK_PROVIDER=httpsms` sends a text through the httpSMS app on the club's Android phone when Twilio refuses it, or when Twilio reports it failed because the toll-free number isn't verified (errors 30032/30034), which covers the time before verification is approved or if it's rejected. Install the httpSMS app on that phone and sign in, copy the API key from https://httpsms.com/settings, and set `HTTPSMS_API_KEY` and `HTTPSMS_FROM_NUMBER` (the phone's number, e.g. `+16205550100`). In httpSMS, add a webhook to `https://app.kiowagunclub.org/api/webhooks/sms/httpsms` for the `message.phone.sent`, `message.phone.delivered`, `message.send.failed` and `message.send.expired` events with a random signing key, and set it as `HTTPSMS_WEBHOOK_SIGNING_KEY`. Keep the phone powered and online. The carrier email gateway (`SMS_PROVIDER=gateway`, with `VERIPHONE_API_KEY`) is also supported, but isn't used.

## 2. Create the Render Blueprint

In Render: **New → Blueprint**, then choose this repository. Render asks for every `sync: false` value:

| Variable | Value |
|---|---|
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | From Stripe |
| `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `EMAIL_FROM_ADDRESS`, `EMAIL_REPLY_TO` | From Resend/domain setup |
| `HTTPSMS_API_KEY` | From https://httpsms.com/settings |
| `HTTPSMS_FROM_NUMBER` | The club phone's number, e.g. `+16205550100` |
| `HTTPSMS_WEBHOOK_SIGNING_KEY` | The signing key you chose for the httpSMS webhook |
| `SENTRY_DSN` | Optional, for error monitoring |
| `TRUSTED_PROXY_COUNT` | Optional, default `1` (Render's load balancer). Set `2` only if the API domain is also behind Cloudflare's proxy. Rate limits and recorded IP addresses count this many entries from the right of `X-Forwarded-For`; the left side is controlled by the visitor |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_NAME`, `BOOTSTRAP_ADMIN_PASSWORD` | The first administrator |

These are set on `kiowa`; `kiowa-daily-jobs` reads them from there, so each is entered once. Render only asks during the initial Blueprint creation; to rotate a secret later, change it on `kiowa` in the dashboard. `SECRET_KEY` and `CRON_SECRET` are generated by Render, and `DATABASE_URL` is the Neon connection string, entered like the other secrets. The production Blueprint also provisions the persistent disk used for uploaded files.

The API refuses to start in production without PostgreSQL, a strong `SECRET_KEY`, the configured Render disk, https CORS origins, and real email/SMS providers.

**After the first successful deploy, delete `BOOTSTRAP_ADMIN_PASSWORD`.**

## 3. Scheduled jobs

`kiowa-daily-jobs` runs once a day:

| Job | What it does | Safe to repeat? |
|---|---|---|
| `nra-check` | Marks members whose NRA expiration date has passed as NRA-inactive (blocks payment until the board verifies new proof) | Yes |
| `renewal-reminders` | 45- and 15-day dues reminders by email (and by text to members who opted in) | Yes. Each (member, cycle, threshold, channel) is recorded once |
| `termination-sweep` | The day after the cutoff, moves unpaid members to Terminated and deletes their private documents; emails the board a summary | Yes. Runs once per year (`job_runs` table) |
| `reconcile-payments` | Asks Stripe about checkouts still pending after 30 minutes, in case a webhook was missed | Yes |
| `purge-sessions` | Deletes expired sessions | Yes |

Run one by hand from the `kiowa-daily-jobs` or `kiowa` shell: `python -m app.jobs renewal-reminders`. You can also trigger jobs over HTTP: `curl -X POST -H "Authorization: Bearer $CRON_SECRET" https://app.kiowagunclub.org/api/jobs/daily`.

## 4. Static sites

Each app is a Render static site in the Blueprint:

| Service | Builds | Custom domain |
|---|---|---|
| `www` | `apps/www` | `www.kiowagunclub.org` (the apex `kiowagunclub.org` still points at the old Wix site) |
| `portal` | `apps/portal` | `portal.kiowagunclub.org` |
| `apply` | `apps/apply` | `apply.kiowagunclub.org` |
| `board` | `apps/board` | `board.kiowagunclub.org` |

- **Build** runs from the repository root: `npm ci --prefix apps/<app> && npm run build --prefix apps/<app>`, publishing `apps/<app>/dist`. The sites don't use `rootDir`, because Render hides files outside a root directory from the build and every app imports `apps/shared`. Each site's `buildFilter` redeploys it when its own folder or `apps/shared` changes.
- **Node version** is set by `NODE_VERSION` in `render.yaml` (Vite 8 needs 22.12+). Keep it in step with each app's `.node-version`.
- **Environment variables** are optional. Production builds already link to the real addresses (see `apps/shared/urls.ts` and `apps/shared/api.ts`). To point an app somewhere else, add `VITE_API_BASE_URL`, `VITE_WWW_URL`, `VITE_PORTAL_APP_URL`, `VITE_APPLY_APP_URL` or `VITE_BOARD_APP_URL` to that site's `envVars`. Vite builds them into the bundle, so changing one needs a redeploy.
- **Security headers** (CSP, HSTS, etc.) and long-lived caching for `/assets/*` are set under each site's `headers` in `render.yaml`. If the API domain changes, update the CSP there.
- **SPA routing** uses a `/* -> /index.html` rewrite. Render serves real files first, so assets are unaffected. **A rewrite in `render.yaml` only reaches a static site that was created from (or linked to) the Blueprint.** For services that already existed, add it by hand: each static site's **Redirects/Rewrites** tab → **Add Rule** → type *Rewrite*, source `/*`, destination `/index.html`. Without it, only `/` loads: every other address typed or clicked as a full page load (emailed links, the redirect after submitting an application, the return from Stripe) is a 404 from Render, although clicking around inside an already-loaded app works. Check with `curl -I https://portal.kiowagunclub.org/login` — it should say `200`.
- **Use the custom domain**, not `*.onrender.com`. The API only accepts the origins in `CORS_ORIGINS`, and its session cookies are only sent between sites under `kiowagunclub.org`.

### DNS

The Blueprint attaches all five domains, but you still create the DNS records at your DNS provider. Render shows the exact records in each service's **Settings → Custom Domains**: a CNAME to `<service>.onrender.com` for each subdomain, and an A record (or ALIAS/flattened CNAME) for the apex `kiowagunclub.org`. If the DNS is on Cloudflare, set the records to **DNS only** (grey cloud) so Render can issue certificates.

## 5. Monitoring

- `GET /health` reports liveness (used by Render). `GET /health/ready` checks the database and the migration version, and reports which integrations are configured.
- Logs are JSON lines with a `request_id`. Every API response carries `X-Request-ID`, and error responses include it, so a member's screenshot of an error can be matched to the log line.
- Set `SENTRY_DSN` to send unhandled errors to Sentry. Personal data is not sent.
- Payment webhook problems appear in the logs as `stripe_webhook_rejected`, `stripe_amount_mismatch` or `stripe_session_unmatched`.

## 6. Backups and recovery

- **Database.** The database is on Neon. Keep a Neon plan whose point-in-time restore window covers how far back the club may need to recover.
- **Files.** The API uses the Render persistent disk at `/var/data/kiowa-storage`. Render's persistent-disk snapshots provide recovery protection; maintain an additional export/backup if the club's document retention requirements warrant it.
- **Secrets.** Keep every `sync: false` value in the club's password manager.
- **Test a restore** at least once a year.

## 7. Scaling notes

The API keeps login rate-limit counters in memory, per process (2 workers means 2 counters). Account lockouts are stored in the database and are exact. If the API is ever scaled to more instances, move the rate limiter to a shared store. The persistent disk requires `kiowa` to remain at one instance; Render does not support scaling a service with an attached disk.
