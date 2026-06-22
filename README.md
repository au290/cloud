# MiniStack Storage Portal

A self-service "rent-a-bucket" cloud storage platform, built to the design in
[`SKILL.md`](SKILL.md). Users register, the system auto-provisions an isolated S3
bucket + Access/Secret keys in **MiniStack** (a Docker-free AWS emulator), and they
upload/list/download/delete objects against a byte quota set by their subscription
package.

## Stack

| Layer | Tech |
|-------|------|
| Frontend | Static HTML + vanilla JS (`frontend/`) — quota bar, file manager, credential reveal |
| API | **Flask** JSON API under `/api/*` (`backend/`) |
| Data | SQLAlchemy → PostgreSQL |
| Engine | MiniStack `:4566` — S3 (storage) + IAM (keys) |
| Worker | `backend/worker.py` — periodic quota reconciliation |

## Architecture

```
Browser ──REST+JWT──> Flask API ──SQL──────> PostgreSQL
                          │
                          └──S3+IAM(boto3)──> MiniStack :4566
Power user CLI/SDK ─direct, own key────────> MiniStack :4566
Worker ─recompute used_bytes───────────────> MiniStack + DB
```

Two access layers share one MiniStack instance: the **UI layer** (backend calls S3 on
the user's behalf, enforcing quota + logging) and the **key layer** (technical users
use their own Access/Secret keys with boto3 / AWS CLI / rclone).

## Quick start

```bash
# One-time setup
pip install ministack                       # the Docker-free AWS emulator
cd backend
python -m venv venv && source venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
createdb iaas                               # PostgreSQL must be running
# configure ../.env (DATABASE_URL, MINISTACK_*, JWT_SECRET, FERNET_KEY)

# Start everything with one command (from the project root):
cd ..
python run.py                               # MiniStack + Flask API + worker
#   -> Portal at http://localhost:8000   (Ctrl+C stops all services)

# Try it (separate terminal)
python demo.py                              # end-to-end API smoke test
```

`run.py` supervises all three services and shuts them down together on Ctrl+C.
PostgreSQL is a prerequisite (the launcher checks it's reachable but does not start
it). Flags: `--no-ministack` (run MiniStack yourself), `--no-worker`.

To run a service on its own instead:

```bash
cd backend
python app.py        # API + frontend only
python worker.py     # reconciliation worker only
```

Default admin (seeded): `admin@iaas.local` / `admin123` → `/admin.html`.

The platform runs on **PostgreSQL only** — create the database first
(`CREATE DATABASE iaas;`) and point `DATABASE_URL` at it. Without MiniStack reachable,
provisioning still mints local AWS-style keys but object operations fail until
MiniStack is up.

## API (see SKILL.md §7)

`POST /api/register` · `POST /api/login` · `GET /api/me` · `GET /api/packages` ·
`GET|POST /api/subscriptions` · `GET|POST /api/credentials` ·
`GET|POST /api/objects` · `GET|DELETE /api/objects/<key>` · `GET /api/logs` ·
admin: `GET /api/admin/{stats,users,logs}`.

## Tests

```bash
createdb iaas_test              # one-time: tests use a dedicated DB
cd backend
python -m pytest tests/ -q      # Flask test client, Postgres iaas_test + MiniStack fake
```
