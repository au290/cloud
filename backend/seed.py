"""Seed the 3+ storage packages (skill: "at least 3") and a default admin user."""
import os

from database import SessionLocal, engine, Base
from models import Package, User, UserStatus

GB = 1024 ** 3

PACKAGES = [
    dict(name="Free",  quota_bytes=1 * GB,    max_buckets=1, price=0.00,
         description="1 GB object storage. Great for trying things out."),
    dict(name="Basic", quota_bytes=50 * GB,   max_buckets=1, price=5.00,
         description="50 GB object storage. S3-compatible via MiniStack."),
    dict(name="Pro",   quota_bytes=500 * GB,  max_buckets=3, price=25.00,
         description="500 GB object storage with up to 3 buckets."),
]


def seed_packages():
    db = SessionLocal()
    try:
        if db.query(Package).count() > 0:
            return
        db.add_all([Package(**p) for p in PACKAGES])
        db.commit()
        print(f"Seeded {len(PACKAGES)} storage packages.")
    finally:
        db.close()


def seed_admin():
    from security import hash_password
    db = SessionLocal()
    try:
        email = os.getenv("ADMIN_EMAIL", "admin@iaas.local")
        if db.query(User).filter(User.email == email).first():
            return
        db.add(User(
            username="admin",
            email=email,
            password_hash=hash_password(os.getenv("ADMIN_PASSWORD", "admin123")),
            status=UserStatus.active,
            is_admin=True,
        ))
        db.commit()
        print(f"Admin user created: {email} / admin123")
    finally:
        db.close()


def run():
    Base.metadata.create_all(bind=engine)
    seed_packages()
    seed_admin()


if __name__ == "__main__":
    run()
