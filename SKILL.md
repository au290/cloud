---
name: iaas-ministack-storage-design
description: Design the architecture and database for a self-service cloud storage provider portal backed by MiniStack (a pip-installable, Docker-free AWS emulator). Use this skill whenever building or documenting an S3-style "rent-a-bucket" platform where users register, get an isolated bucket, receive Access/Secret keys, and consume storage against a quota — including the system architecture (frontend, API, DB, emulator, worker) and the relational schema (users, packages, subscriptions, buckets, credentials, objects, logs). Trigger this even when the user only says "design the database", "draw the architecture", or "how should this storage platform be structured", as long as the context is a MiniStack/LocalStack/MinIO S3-bucket rental system.
---

# IaaS / MiniStack Storage Platform — Design

How to design a self-service storage provider portal: users sign up, the system auto-provisions an isolated S3 bucket and credentials in MiniStack, and users consume storage against a quota tied to a subscription package.

## 1. Scope

The platform provides:
- Registration / login.
- A dashboard showing remaining quota, rented services, and Access/Secret keys (shown securely).
- Storage rental: upload / list / download / delete objects.
- Subscription packages (at least 3) that set the storage quota.
- Per-user isolated bucket + per-user IAM-style credentials.
- An activity log of rentals and access.

Engine: **MiniStack** — an open-source AWS emulator, drop-in replacement for LocalStack. It runs **without Docker** via pip and serves the S3 + IAM + STS APIs on port `4566`.

```bash
pip install ministack
ministack            # http://localhost:4566
```
Set `PERSIST_STATE` so buckets/objects survive restarts (important for demos).

## 2. Architecture

Run everything natively (no Docker required):

| Layer | Component | Notes |
|-------|-----------|-------|
| Client | Browser (normal user) | uses the dashboard UI only |
| Client | Power user (CLI / SDK / rclone) | uses Access/Secret keys directly |
| App | Frontend (HTML + vanilla JS) | dashboard, file manager; optionally htmx or Alpine.js for dynamic parts, no build step |
| App | Backend API (Flask) | auth, quota enforcement, S3 wrapper; can also serve the HTML via Jinja2 |
| Data | PostgreSQL (or SQLite) | users, packages, logs |
| Engine | MiniStack `:4566` | S3 (storage) + IAM (keys) |
| Job | Worker | periodic quota recalculation |

### Diagram (text form — readable by Claude Code)
```mermaid
graph TD
  B[Browser] --> R[HTML + vanilla JS]
  R -->|REST + JWT| A[Flask API]
  A -->|SQL| D[(PostgreSQL)]
  A -->|S3 + IAM via boto3| M[MiniStack :4566]
  P[Power user CLI/SDK] -.->|direct, uses key| M
  W[Worker] -->|recalc usage| M
  W -->|update used_bytes| D
```

### Relations (who calls whom)
| From | To | Protocol | Purpose | Mode |
|------|----|----------|---------|------|
| Browser | Frontend | HTTPS | load UI | sync |
| Frontend | Flask API | REST/JSON + JWT | every user action | sync |
| Flask API | PostgreSQL | SQL (SQLAlchemy/psycopg2) | users, packages, subs, credentials, objects, logs | sync |
| Flask API | MiniStack | S3 + IAM (boto3) `:4566` | create bucket/keys, put/get/list/delete | sync |
| Power user | MiniStack | S3 (boto3 / CLI / rclone) | direct access with own key, bypasses API | sync |
| Worker | MiniStack | S3 list | recompute real usage | scheduled |
| Worker | PostgreSQL | SQL | update `used_bytes` | scheduled |

**Startup/dependency order:** PostgreSQL and MiniStack must be up first → then Flask API → then the frontend. The Worker depends on both PostgreSQL and MiniStack and runs outside the request path (scheduled). All API↔DB and API↔MiniStack calls are synchronous request/response.

### Data flows
1. **Normal path:** Browser → HTML/JS frontend → Flask API. All storage actions go through the API so quota and logging are enforced.
2. **API → PostgreSQL:** persist users, subscriptions, credentials, object metadata, logs.
3. **API → MiniStack (S3 + IAM):** create bucket, generate keys, put/list/get objects.
4. **Power-user path:** Power user → MiniStack **directly** with their Access/Secret key, bypassing the API. This is why the Worker exists.
5. **Worker → MiniStack + DB:** recompute real usage from the bucket and update `used_bytes`, so quota stays accurate even after direct (bypassing) access.

### Two access layers (design decision)
Storage in MiniStack is object storage (S3), accessed via the S3 API. Wrap it in two layers:
- **UI layer** (dashboard file manager, plain HTML + vanilla JS using `fetch`) for non-technical users — the backend calls MiniStack on their behalf.
- **API/key layer** for technical users — they use their own credentials with boto3, AWS CLI, rclone, etc. (`--endpoint-url http://localhost:4566`).

Both hit the same MiniStack instance.

### boto3 reference
```python
import boto3
s3 = boto3.client("s3",
    endpoint_url="http://localhost:4566",
    aws_access_key_id="admin", aws_secret_access_key="admin",
    region_name="us-east-1")
s3.create_bucket(Bucket="bucket-user-1")
s3.put_object(Bucket="bucket-user-1", Key="hello.txt", Body=b"hi")
```

## 3. Quota model

MiniStack/S3 has **no built-in storage quota** — enforce it in the application:

- **Quota = subscription's package limit.** Stored as `packages.quota_bytes`.
- **Usage** is tracked two ways:
  - Fast: a `used_bytes` counter on the subscription, updated on each upload/delete.
  - Accurate: sum object sizes from MiniStack (`list_objects_v2` → `Size`) — run by the Worker to reconcile, especially after direct key access.
- **Remaining** shown on the dashboard = `quota_bytes − used_bytes`.
- **Enforcement:** before upload, reject if `used_bytes + new_file_size > quota_bytes`.

## 4. Database schema (DBML)

Paste into https://dbdiagram.io. PostgreSQL-friendly types.

```dbml
Enum user_status { active suspended }
Enum sub_status  { active expired cancelled }
Enum cred_status { active revoked }
Enum log_action  { register subscribe bucket_created key_generated upload download delete quota_exceeded }

Table users {
  id            int          [pk, increment]
  username      varchar      [not null, unique]
  email         varchar      [not null, unique]
  password_hash varchar      [not null]
  status        user_status  [not null, default: 'active']
  created_at    timestamp    [default: `now()`]
}

Table packages {                       // seed at least 3 rows: Free / Basic / Pro
  id          int      [pk, increment]
  name        varchar  [not null, unique]
  quota_bytes bigint   [not null]
  max_buckets int      [not null, default: 1]
  price       numeric  [not null, default: 0]
  description varchar
}

Table subscriptions {
  id          int        [pk, increment]
  user_id     int        [not null, ref: > users.id]
  package_id  int        [not null, ref: > packages.id]
  used_bytes  bigint     [not null, default: 0]
  status      sub_status [not null, default: 'active']
  started_at  timestamp  [default: `now()`]
  expires_at  timestamp
}

Table buckets {                        // isolated bucket per user in MiniStack
  id              int       [pk, increment]
  user_id         int       [not null, ref: > users.id]
  subscription_id int       [ref: > subscriptions.id]
  name            varchar   [not null, unique]
  region          varchar   [not null, default: 'us-east-1']
  created_at      timestamp [default: `now()`]
}

Table credentials {                    // Access Key + Secret Key per user
  id                   int         [pk, increment]
  user_id              int         [not null, ref: > users.id]
  access_key_id        varchar     [not null, unique]
  secret_key_encrypted varchar     [not null]    // never store plaintext
  status               cred_status [not null, default: 'active']
  created_at           timestamp   [default: `now()`]
}

Table objects {                        // optional: file metadata for listing + reconciliation
  id           int       [pk, increment]
  bucket_id    int       [not null, ref: > buckets.id]
  object_key   varchar   [not null]
  size_bytes   bigint    [not null, default: 0]
  content_type varchar
  uploaded_at  timestamp [default: `now()`]

  indexes {
    (bucket_id, object_key) [unique]
  }
}

Table activity_logs {
  id         int        [pk, increment]
  user_id    int        [not null, ref: > users.id]
  action     log_action [not null]
  detail     varchar
  bytes      bigint
  created_at timestamp  [default: `now()`]
}
```

### Schema decisions
- `packages`: seed with 3+ rows so the "minimum 3 services" requirement is met; quota lives here.
- Remaining quota is derived: `packages.quota_bytes − subscriptions.used_bytes`.
- `credentials.secret_key_encrypted`: encrypt (e.g. Fernet/AES) before insert; show the secret **once** at creation time, mirroring AWS.
- `objects` is optional but valuable: it powers fast file-manager listing and lets the Worker recompute `used_bytes` without hammering MiniStack.
- For strict "one active subscription per user", add a partial unique index on `subscriptions(user_id) WHERE status='active'` in the migration (dbdiagram won't render partial indexes).

## 5. Provisioning flow (registration)

On sign-up the backend should, in one transaction-ish sequence:
1. Insert `users` row.
2. Insert `subscriptions` row for the chosen package.
3. Call MiniStack to create an isolated bucket → insert `buckets` row.
4. Call MiniStack IAM (or generate locally) to mint Access/Secret keys → insert `credentials` (secret encrypted).
5. Log `register`, `bucket_created`, `key_generated` in `activity_logs`.

Verify whether MiniStack's IAM `create_access_key` is fully implemented; if it is only a stub, generate keys in the backend (e.g. `secrets.token_*`), store them, and map them to the user's bucket.

## 6. Build order (suggested)
1. DB schema + seed packages.
2. MiniStack running via pip; confirm bucket + object round-trip with boto3.
3. Flask: auth (JWT), registration provisioning flow, S3 wrapper endpoints (upload/list/download/delete) with quota checks.
4. Frontend (HTML + vanilla JS, optionally htmx/Alpine.js): quota bar, file manager, credential reveal. Serve as static files or via Flask/Jinja2.
5. Worker: scheduled reconciliation of `used_bytes`.

JWT secures the frontend ↔ API calls; Access/Secret keys are separate and only for the S3/direct-access layer.

## 7. API contract & configuration

Endpoints the frontend calls (all JSON, JWT-protected except auth). Adjust names to taste, but keep the contract explicit so the implementation stays consistent.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/register` | create user → provision bucket + keys; returns secret once |
| POST | `/api/login` | returns JWT |
| GET | `/api/me` | current user, package, quota, `used_bytes` |
| GET | `/api/packages` | list available packages (≥3) |
| POST | `/api/subscriptions` | subscribe to a package |
| GET | `/api/credentials` | list Access Key IDs (never returns secret again) |
| POST | `/api/credentials` | mint a new key pair (secret shown once) |
| GET | `/api/objects` | list objects in the user's bucket |
| POST | `/api/objects` | upload (enforce quota before put) |
| GET | `/api/objects/{key}` | download / presigned URL |
| DELETE | `/api/objects/{key}` | delete object |
| GET | `/api/logs` | recent activity log |

### Environment variables
```
DATABASE_URL=postgresql://user:pass@localhost:5432/iaas   # or sqlite:///iaas.db
MINISTACK_ENDPOINT=http://localhost:4566
AWS_DEFAULT_REGION=us-east-1
MINISTACK_ADMIN_KEY=admin            # backend's own credentials for provisioning
MINISTACK_ADMIN_SECRET=admin
JWT_SECRET=change-me
FERNET_KEY=...                        # to encrypt stored secret keys
QUOTA_RECALC_INTERVAL=300            # worker interval, seconds
```

### Wiring notes for implementation
- The backend holds **admin** MiniStack credentials (`MINISTACK_ADMIN_*`) to create buckets/keys; each user's own key pair is stored encrypted and used only for that user's direct-access layer.
- Quota check belongs in `POST /api/objects`: reject when `used_bytes + size > packages.quota_bytes`.
- The Worker reads `MINISTACK_ENDPOINT` + `DATABASE_URL` and reconciles `used_bytes` every `QUOTA_RECALC_INTERVAL`.
