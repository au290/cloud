import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session
from dotenv import load_dotenv

load_dotenv()

# Single source of truth for the connection string (SKILL.md §7). PostgreSQL only.
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:user@localhost:5432/iaas")

if not DATABASE_URL.startswith("postgresql"):
    raise RuntimeError(
        f"DATABASE_URL must be a PostgreSQL URL (got {DATABASE_URL!r}). "
        "This platform runs on PostgreSQL only."
    )

engine = create_engine(
    DATABASE_URL,
    pool_size=20,        # base persistent connections
    max_overflow=40,     # burst headroom
    pool_pre_ping=True,  # discard stale connections before checkout
    pool_recycle=1800,   # recycle connections older than 30 min
)

# scoped_session gives each request/thread its own Session; Flask tears it down
# per request (see app.teardown_appcontext). Workers create their own SessionLocal.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)

Base = declarative_base()
Base.query = db_session.query_property()
