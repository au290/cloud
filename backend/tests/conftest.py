import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    # SQLAlchemy ignores postgresql_where on SQLite, creating a non-partial unique index.
    # Drop and recreate it as a proper partial index so re-renting after release works.
    with engine.connect() as conn:
        conn.execute(sa_text("DROP INDEX IF EXISTS uq_active_sub_per_package"))
        conn.execute(sa_text(
            "CREATE UNIQUE INDEX uq_active_sub_per_package "
            "ON user_subscriptions(user_id, package_id) "
            "WHERE status = 'active'"
        ))
        conn.commit()
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def mock_ministack():
    iam_mock = MagicMock()
    iam_mock.create_user.return_value = {}
    _counter = [0]

    def _make_key(**kwargs):
        _counter[0] += 1
        return {"AccessKey": {"AccessKeyId": f"AKIA{_counter[0]:016d}", "SecretAccessKey": f"secret{_counter[0]}"}}

    iam_mock.create_access_key.side_effect = _make_key

    s3_mock = MagicMock()
    s3_mock.list_buckets.return_value = {"Buckets": []}
    s3_mock.head_bucket.side_effect = Exception("NoSuchBucket")
    s3_mock.create_bucket.return_value = {}

    ssm_mock = MagicMock()
    ssm_mock.put_parameter.return_value = {}

    with patch("ministack_client.get_iam", return_value=iam_mock), \
         patch("ministack_client.get_s3", return_value=s3_mock), \
         patch("ministack_client.get_ssm", return_value=ssm_mock):
        yield {"iam": iam_mock, "s3": s3_mock, "ssm": ssm_mock}


@pytest.fixture()
def client(db_session, mock_ministack):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_packages(db_session):
    from models import SubscriptionPackage, PackageType
    packages = [
        SubscriptionPackage(name="Basic Compute", type=PackageType.compute,
                            quota_value=2, quota_unit="vCPU", price=10.00,
                            description="2 vCPUs"),
        SubscriptionPackage(name="Basic Storage", type=PackageType.storage,
                            quota_value=50, quota_unit="GB", price=5.00,
                            description="50GB storage"),
        SubscriptionPackage(name="Basic Network", type=PackageType.network,
                            quota_value=100, quota_unit="Mbps", price=15.00,
                            description="100 Mbps"),
    ]
    db_session.add_all(packages)
    db_session.commit()
    for p in packages:
        db_session.refresh(p)
    return packages


@pytest.fixture()
def admin_headers(client, db_session):
    resp = client.post("/auth/register", json={
        "full_name": "Admin User",
        "email": "admin@example.com",
        "password": "adminpass123",
    })
    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]
    from models import User
    user = db_session.query(User).filter(User.id == user_id).first()
    user.is_admin = True
    db_session.commit()
    login = client.post("/auth/login", data={"username": "admin@example.com", "password": "adminpass123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def registered_user(client):
    resp = client.post("/auth/register", json={
        "full_name": "Test User",
        "email": "test@example.com",
        "password": "testpass123",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture()
def auth_headers(client, registered_user):
    resp = client.post("/auth/login", data={
        "username": "test@example.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
