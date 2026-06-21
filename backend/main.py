import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from database import engine, Base
import models  # noqa: F401 — registers all tables with Base.metadata
from routers import auth, packages, rentals, dashboard, admin

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE NOT NULL"
            ))
            conn.execute(text(
                "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS resource_ref VARCHAR(255)"
            ))
            conn.execute(text(
                "ALTER TABLE user_subscriptions ADD COLUMN IF NOT EXISTS quota_used INTEGER NOT NULL DEFAULT 0"
            ))
            conn.execute(text(
                "ALTER TABLE rental_logs ADD COLUMN IF NOT EXISTS subscription_id INTEGER REFERENCES user_subscriptions(id)"
            ))
            # Create indexes defined in models that create_all() won't add to existing tables
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_subs_user_status ON user_subscriptions(user_id, status)"
            ))
            conn.execute(text(
                """CREATE UNIQUE INDEX IF NOT EXISTS uq_active_sub_per_package
                   ON user_subscriptions(user_id, package_id)
                   WHERE status = 'active'"""
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_log_user_ts ON rental_logs(user_id, timestamp)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_cred_user_active ON access_credentials(user_id, is_active)"
            ))
            conn.commit()
        print("Database tables created/verified OK")
        from seed import run as seed_packages
        seed_packages()
    except Exception as e:
        print(f"WARNING: Could not connect to database: {e}")
    yield


app = FastAPI(title="IaaS Portal", version="1.0.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(packages.router)
app.include_router(rentals.router)
app.include_router(dashboard.router)
app.include_router(admin.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    from sqlalchemy import text

    db_ok = False
    minio_ok = False

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        from ministack_client import get_s3
        get_s3().list_buckets()
        minio_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if (db_ok and minio_ok) else "degraded",
        "database": "connected" if db_ok else "unreachable",
        "ministack": "connected" if minio_ok else "unreachable",
    }


FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
