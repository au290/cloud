from tests.conftest import register


def test_register_provisions_bucket_and_secret(client, fake_ms):
    res = register(client)
    assert res.status_code == 201, res.get_data(as_text=True)
    body = res.get_json()
    assert body["user"]["username"] == "alice"
    assert body["bucket"]["name"] == "bucket-user-" + str(body["user"]["id"])
    # Secret key is returned exactly once at creation.
    assert body["secret_key"]
    assert body["access_key_id"]
    # Bucket really exists in (fake) MiniStack.
    assert body["bucket"]["name"] in fake_ms.buckets


def test_register_duplicate_email_rejected(client):
    register(client)
    res = register(client, username="alice2")
    assert res.status_code == 400


def test_login_and_me(client):
    register(client)
    login = client.post("/api/login", json={"email": "alice@example.com", "password": "password123"})
    assert login.status_code == 200
    token = login.get_json()["access_token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    data = me.get_json()
    assert data["user"]["email"] == "alice@example.com"
    assert data["subscription"]["package"]["name"] == "Free"


def test_login_wrong_password(client):
    register(client)
    res = client.post("/api/login", json={"email": "alice@example.com", "password": "nope"})
    assert res.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/me").status_code == 401
