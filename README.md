# Vehicle Maintenance API

[![CI](https://github.com/lmartinezcarbo/vehicle-maintenance-api/actions/workflows/ci.yml/badge.svg)](https://github.com/lmartinezcarbo/vehicle-maintenance-api/actions/workflows/ci.yml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

REST API for managing vehicles, maintenance records, parts, expenses and
payments for a workshop.

Built as a backend portfolio project to demonstrate practical experience
with Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, authentication,
role-based authorization, payment integration, automated testing, CI and
Docker.

Interactive documentation is served at `/docs` (Swagger UI) and `/redoc`.

## Live demo

* API (production): <https://vehicle-maintenance-api-f3jn.onrender.com>
  — health check at `/health`, interactive docs at `/docs`
* Web frontend: <https://vehicle-maintenance-frontend-nine.vercel.app>

The API runs on Render's free tier, so the first request after a quiet
period can take **30–60 seconds** to wake up; `/health` is instant once it
is warm.

### Demo data

Three public demo accounts live in production (they exist to be demoed;
the 2FA code arrives by email within minutes):

| Role | Email | Password |
| --- | --- | --- |
| `customer` — owns the demo vehicle and pays | `lmartinezcarbo1994@gmail.com` | `ProdDemo-2026-vmapi` |
| `mechanic` | `lmartinezcarbo@gmail.com` | `MechDemo-2026-vmapi` |
| `admin` | `lmartinezcarbo+admin@gmail.com` | `AdminDemo-2026-vmapi` |

Behind them sits one verified Toyota Corolla, one `completed` maintenance
record ("Oil change", $89.99 of labor) and its `paid` payment — exactly
what `scripts/seed.py` creates on a fresh database:

```bash
python scripts/seed.py      # insert-only and idempotent; run from the repo root
```

The vehicle photo is the single piece the seed leaves out: it lives on
Cloudinary and is uploaded once through the UI.

## Features

* User registration with email verification and login with a emailed 2FA code
* JWT access tokens plus refresh tokens with rotation, reuse detection and logout
* Role-based authorization (`customer`, `mechanic`, `admin`) combined with
  ownership checks
* Vehicle management with a verification step performed by workshop staff
* Maintenance records with a lifecycle: `in_progress` → `ready` → `completed`
* Parts catalog (admin) and parts attached to a maintenance record
* Expense tracking per vehicle
* Stripe Checkout payments: open a checkout, receive the webhook, the payment
  becomes `paid` and the record `completed`, and the customer gets a
  confirmation email
* Input validation with Pydantic, filtering, pagination, sorting and search
* Rate limiting on every write endpoint (slowapi, per client), including
  profile and role management: 20/minute on workshop resources,
  10/minute on profile edits and token refresh, 3–5/minute on auth,
  role changes and account deletes
* Uniform authorization refusals: one response per endpoint, the real reason
  is written to the log
* Input-driven HTTP status codes (`201`, `409`, `422`, ...) instead of `500`
* Automated tests with pytest, GitHub Actions CI, dependency audit with
  pip-audit, health check, application logging
* Docker and Docker Compose support, Swagger UI and ReDoc

## Tech stack

| Area | Tools |
| --- | --- |
| Backend | Python 3.14, FastAPI, Pydantic, SQLAlchemy (ORM), Uvicorn |
| Database | PostgreSQL 17, Alembic migrations |
| Auth & security | JWT (PyJWT), pwdlib/Argon2 password hashing, HMAC-SHA256 refresh token digests, RBAC + ownership, slowapi rate limiting |
| Payments | Stripe Checkout + signed webhooks |
| Email | Brevo (transactional email: verification, 2FA, payment receipt) |
| Testing | pytest (123 tests) |
| CI & tooling | GitHub Actions (tests, `alembic check`, `pip-audit`), Docker, Docker Compose, Git |

## Getting started

### Requirements

* Python 3.14 (for running the suite locally)
* Docker with Docker Compose (PostgreSQL 17 is started for you)

### Environment variables

Copy the names below into a local `.env` (the file is gitignored, so real
values never reach the repository):

| Variable | Used by | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | app | Key that signs access tokens and refresh token digests |
| `DATABASE_URL` | app, alembic | `postgresql+psycopg://user:password@host:5432/dbname` |
| `TEST_DATABASE_URL` | pytest | Test database; the suite drops its schema and rebuilds it with the real migrations on every run |
| `BREVO_API_KEY` | app | Brevo API key for transactional email |
| `EMAIL_FROM` | app | Sender address for outgoing email |
| `STRIPE_SECRET_KEY` | app | Stripe API key |
| `STRIPE_SUCCESS_URL` | app | Redirect after a successful checkout |
| `STRIPE_CANCEL_URL` | app | Redirect after a cancelled checkout |
| `STRIPE_WEBHOOK_SECRET` | app | Secret used to verify webhook signatures |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | docker-compose | Credentials of the database container |

`ALGORITHM` and `CORS_ORIGINS` have defaults (`HS256`, `http://localhost:3000`)
and can be omitted.

### Run the API

```bash
docker compose up -d --build              # api + postgres
docker compose exec -T api alembic upgrade head   # migrations
# API on http://localhost:8000  (docs: /docs)
```

The container starts Uvicorn only; migrations are an explicit step, so a
schema change is never applied by surprise.

## Authentication

1. `POST /users/` → `201`, an email with a verification code is sent
2. `POST /users/verify-email` `{email, code}`
3. `POST /users/login` (form fields `username`, `password`) → responds
   `requires_2fa: true` and emails a second code
4. `POST /users/verify-2fa` `{email, code}` → returns `access_token` and
   `refresh_token`
5. Send `Authorization: Bearer <access_token>` on every request
6. `POST /users/refresh` `{refresh_token}` → a **new** token pair; the old
   refresh token is retired
7. `POST /users/logout` `{refresh_token}` revokes that session

Presenting a refresh token that was already rotated is treated as theft:
the whole token family is revoked and the request gets `401`. Expired rows
are pruned where new sessions are minted, and the three lookups
(`user_id`, `family_id`, `expires_at`) are indexed.

The bundled web frontend stores the token pair in `localStorage` — simple,
but readable by any script on the page. A deployment handling real money
would move the refresh token into an `httpOnly` cookie; here the trade-off
is deliberate and documented rather than hidden.

## Trying it with curl

```bash
API=https://vehicle-maintenance-api-f3jn.onrender.com

# 1. Log in (form-encoded): answers {"requires_2fa": true} and emails a code
curl -s -X POST "$API/users/login" \
  -d 'username=lmartinezcarbo@gmail.com' -d 'password=MechDemo-2026-vmapi'

# 2. Swap the emailed code for tokens
curl -s -X POST "$API/users/verify-2fa" -H 'Content-Type: application/json' \
  -d '{"email":"lmartinezcarbo@gmail.com","code":"123456"}'

TOKEN='<access_token from the response>'

# 3. Authenticated request
curl -s "$API/vehicles/" -H "Authorization: Bearer $TOKEN"

# 4. A business rule in action: the mileage floor answers 400
#    "Maintenance mileage cannot be lower than the vehicle mileage"
curl -s -X POST "$API/maintenance-records/" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"vehicle_id":1,"service_type":"Oil change","description":"demo",
       "mileage":100,"service_date":"2026-10-10T00:00:00Z",
       "labor_cost":"20.00"}'
```

Login allows 5 attempts/minute per IP and write endpoints 20/minute, so
step 4 also teaches when you get a `429`.

## Authorization

| Role | Can do |
| --- | --- |
| `customer` | Manage their **own** vehicles, records, parts and expenses; pay their own ready records |
| `mechanic` | Everything on vehicles owned by a `customer`: verify vehicles, create/edit records, attach parts, register expenses |
| `admin` | Everything, including the parts catalog, user management and any record |

Refusals are deliberately uniform: for a given endpoint the status code and
`detail` are identical whether the resource does not exist, belongs to
somebody else, or is off limits by role — so no one can probe ids to learn
what is in the database. The actual reason is logged with the user and the
resource id. A state hint about something the caller already owns (for
example `Customers can only delete unverified vehicles`) is kept, because it
reveals nothing to anyone else.

Once a record leaves `in_progress` it is frozen: its parts and expenses stop
changing, and authorization is always decided **before** state.

## Payments

1. `POST /payments/` with a `ready` record you own → `201` with a
   `checkout_url` (asking again for the same record reuses the open checkout
   and answers `200`)
2. The customer pays on Stripe
3. `POST /payments/webhook` receives the signed event: the payment becomes
   `paid`, the record `completed`, and a receipt email is queued
4. `GET /payments/{id}` returns the payment status

The charged amount is **labor + parts**; expenses are workshop bookkeeping
and never enter the amount. The webhook rejects invalid signatures and any
amount that does not match the stored payment.

## HTTP status codes

| Code | Meaning |
| --- | --- |
| `200` | Success (including handing back an already open checkout) |
| `201` | A resource was created |
| `400` | Business rule not satisfied (wrong state, mileage going backwards, frozen record) |
| `401` | Missing, invalid, expired or revoked credentials |
| `403` | Not authorized — one detail per endpoint, reason in the log |
| `404` | Only on paths the caller is already allowed to use |
| `409` | Conflict with existing data (foreign key still referenced, unique constraint) |
| `422` | Payload that can never be stored (CHECK constraints, out-of-range values) |
| `429` | Rate limit exceeded |
| `500` | Unexpected failure — the real error is in the log |

## Tests and CI

```bash
pytest -q                     # 123 tests against a real PostgreSQL
alembic check                 # migrations match the models
pip-audit -r requirements.txt # known vulnerabilities in pinned deps
```

The suite rebuilds the test schema from the migrations on every run, patches
email out and disables rate limits, so it never sends mail or depends on
timing.

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull
request:

* **tests** — pytest plus `alembic check` against PostgreSQL 17
* **dependency audit** — `pip-audit` over `requirements.txt`

## Project layout

```
app/
  core/          config, security, dependencies, exception handlers, rate limit
  models/        SQLAlchemy models (users, vehicles, records, parts, expenses, payments)
  routers/       one module per resource
  schemas/       Pydantic request/response models
  services/      email, Stripe, maintenance pricing
alembic/         migrations
tests/           pytest suite
scripts/         backup, restore and demo seed
docs/            generated architecture diagram
```

## Documentation

* Swagger UI: `http://localhost:8000/docs`
* ReDoc: `http://localhost:8000/redoc`
* Architecture diagram: `docs/architecture/vehicle-maintenance-api.html` (Archify)
