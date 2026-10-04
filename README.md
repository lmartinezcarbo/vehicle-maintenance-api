# Vehicle Maintenance API

REST API for managing vehicles, maintenance records, parts, expenses and
payments for a workshop.

Built as a backend portfolio project to demonstrate practical experience
with Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, authentication,
role-based authorization, payment integration, automated testing, CI and
Docker.

Interactive documentation is served at `/docs` (Swagger UI) and `/redoc`.

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
* Rate limiting on write endpoints (slowapi, per client); the user profile
  and role management routes rely on authentication and ownership instead
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
| Testing | pytest (97 tests) |
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
pytest -q                     # 97 tests against a real PostgreSQL
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
docs/            generated architecture diagram
```

## Documentation

* Swagger UI: `http://localhost:8000/docs`
* ReDoc: `http://localhost:8000/redoc`
* Architecture diagram: `docs/architecture/vehicle-maintenance-api.html` (Archify)
