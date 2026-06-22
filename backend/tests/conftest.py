"""Test harness: Flask test client over an isolated PostgreSQL DB with MiniStack faked.

Tests run against a dedicated database (default: the local `iaas_test` DB) so they
never touch dev data. Override with TEST_DATABASE_URL. MiniStack is replaced by an
in-memory object store so the storage flow (bucket create, put/get/list/delete,
quota) is exercised without a running emulator.
"""
import os

import pytest

# Point the app at the test database BEFORE importing anything that reads it.
os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL", "postgresql://postgres:user@localhost:5432/iaas_test"
)
os.environ.setdefault("JWT_SECRET", "test-secret")


class FakeMiniStack:
    """Minimal in-memory stand-in for the boto3 S3/IAM calls we make."""
    def __init__(self):
        self.buckets: dict[str, dict[str, bytes]] = {}
        self.types: dict[tuple, str] = {}
        self._key_counter = 0

    def create_bucket(self, name, region="us-east-1"):
        self.buckets.setdefault(name, {})

    def list_objects(self, bucket):
        return [{"key": k, "size": len(v)} for k, v in self.buckets.get(bucket, {}).items()]

    def total_size(self, bucket):
        return sum(len(v) for v in self.buckets.get(bucket, {}).values())

    def put_object(self, bucket, key, body, content_type=None):
        if bucket not in self.buckets:
            raise RuntimeError("NoSuchBucket")  # mirror real S3
        self.buckets[bucket][key] = body
        self.types[(bucket, key)] = content_type

    def upload_fileobj(self, bucket, key, fileobj, content_type=None):
        if bucket not in self.buckets:
            raise RuntimeError("NoSuchBucket")  # mirror real S3
        self.buckets[bucket][key] = fileobj.read()
        self.types[(bucket, key)] = content_type

    def get_object(self, bucket, key):
        if key not in self.buckets.get(bucket, {}):
            raise KeyError(key)
        return self.buckets[bucket][key], self.types.get((bucket, key))

    def delete_object(self, bucket, key):
        self.buckets.get(bucket, {}).pop(key, None)

    def presigned_url(self, bucket, key, expires=300):
        return f"http://localhost:4566/{bucket}/{key}?sig=test"

    def create_user_credentials(self, username):
        self._key_counter += 1
        return {"access_key": f"AKIATEST{self._key_counter:08d}",
                "secret_key": f"secret-{self._key_counter}"}

    def list_buckets(self):
        return list(self.buckets.keys())


@pytest.fixture()
def fake_ms(monkeypatch):
    fake = FakeMiniStack()
    import ministack_client as ms
    for name in ("create_bucket", "list_objects", "total_size", "put_object",
                 "upload_fileobj", "get_object", "delete_object", "presigned_url",
                 "create_user_credentials", "list_buckets"):
        monkeypatch.setattr(ms, name, getattr(fake, name))
    return fake


@pytest.fixture()
def app_ctx(fake_ms):
    from app import create_app
    from database import engine, db_session, Base
    import models  # noqa: F401

    # Fresh schema per test. Postgres honors the partial unique index
    # (postgresql_where) natively, so no manual index fix-up is needed.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    from seed import seed_packages, seed_admin
    seed_packages()
    seed_admin()

    app = create_app(run_init=False)
    app.config.update(TESTING=True)
    yield app
    db_session.remove()


@pytest.fixture()
def client(app_ctx):
    return app_ctx.test_client()


# --- helpers ---------------------------------------------------------------
def register(client, username="alice", email="alice@example.com", password="password123"):
    return client.post("/api/register", json={
        "username": username, "email": email, "password": password,
    })


def auth_headers(client, **kwargs):
    register(client, **kwargs)
    email = kwargs.get("email", "alice@example.com")
    password = kwargs.get("password", "password123")
    res = client.post("/api/login", json={"email": email, "password": password})
    token = res.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def user_headers(client):
    return auth_headers(client)


@pytest.fixture()
def admin_headers(client):
    res = client.post("/api/login", json={"email": "admin@iaas.local", "password": "admin123"})
    token = res.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
