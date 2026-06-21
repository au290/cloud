from database import SessionLocal, engine, Base
from models import SubscriptionPackage, PackageType, User

Base.metadata.create_all(bind=engine)

PACKAGES = [
    SubscriptionPackage(
        name="Basic Compute",
        type=PackageType.compute,
        quota_value=2,
        quota_unit="vCPU",
        price=10.00,
        description="2 virtual CPUs with 4GB RAM. Suitable for small applications.",
    ),
    SubscriptionPackage(
        name="Standard Compute",
        type=PackageType.compute,
        quota_value=8,
        quota_unit="vCPU",
        price=35.00,
        description="8 virtual CPUs with 16GB RAM. Suitable for medium workloads.",
    ),
    SubscriptionPackage(
        name="Basic Storage",
        type=PackageType.storage,
        quota_value=50,
        quota_unit="GB",
        price=5.00,
        description="50GB object storage bucket. S3-compatible via MiniStack.",
    ),
    SubscriptionPackage(
        name="Pro Storage",
        type=PackageType.storage,
        quota_value=500,
        quota_unit="GB",
        price=25.00,
        description="500GB object storage bucket. S3-compatible via MiniStack.",
    ),
    SubscriptionPackage(
        name="Basic Network",
        type=PackageType.network,
        quota_value=100,
        quota_unit="Mbps",
        price=15.00,
        description="100 Mbps dedicated bandwidth with 1TB monthly transfer.",
    ),
]


def seed_packages():
    db = SessionLocal()
    try:
        if db.query(SubscriptionPackage).count() > 0:
            return
        db.add_all(PACKAGES)
        db.commit()
        print(f"Seeded {len(PACKAGES)} subscription packages.")
    finally:
        db.close()


def seed_admin():
    from security import hash_password
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == "admin@iaas.local").first():
            return
        db.add(User(
            full_name="Super Admin",
            email="admin@iaas.local",
            password_hash=hash_password("admin123"),
            is_admin=True,
        ))
        db.commit()
        print("Admin user created: admin@iaas.local / admin123")
    finally:
        db.close()


def run():
    seed_packages()
    seed_admin()


if __name__ == "__main__":
    run()
