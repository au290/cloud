def test_register_succeeds_with_valid_email(client):
    resp = client.post("/auth/register", json={
        "full_name": "Alice", "email": "alice@example.com", "password": "pass123"
    })
    assert resp.status_code == 201
    assert resp.json()["email"] == "alice@example.com"


def test_register_rejects_duplicate_email(client):
    client.post("/auth/register", json={
        "full_name": "Alice", "email": "alice@example.com", "password": "pass123"
    })
    resp = client.post("/auth/register", json={
        "full_name": "Alice2", "email": "alice@example.com", "password": "other"
    })
    assert resp.status_code == 400
    assert "already registered" in resp.json()["detail"].lower()


def test_register_rejects_invalid_email_format(client):
    resp = client.post("/auth/register", json={
        "full_name": "Bad", "email": "notanemail", "password": "pass123"
    })
    assert resp.status_code == 422


def test_register_rejects_dot_local_domain(client):
    # EmailStr uses email-validator which rejects special-use domains like .local
    resp = client.post("/auth/register", json={
        "full_name": "Internal", "email": "user@company.local", "password": "pass123"
    })
    assert resp.status_code == 422


def test_login_with_form_data_succeeds(client, registered_user):
    resp = client.post("/auth/login", data={
        "username": "test@example.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()
    assert resp.json()["token_type"] == "bearer"


def test_login_wrong_password_returns_401(client, registered_user):
    resp = client.post("/auth/login", data={
        "username": "test@example.com",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(client):
    resp = client.post("/auth/login", data={
        "username": "nobody@example.com",
        "password": "anything",
    })
    assert resp.status_code == 401


def test_login_with_json_body_returns_422(client, registered_user):
    # Login requires form data (OAuth2), not JSON
    resp = client.post("/auth/login", json={
        "email": "test@example.com",
        "password": "testpass123",
    })
    assert resp.status_code == 422


def test_me_returns_current_user(client, auth_headers, registered_user):
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "test@example.com"
    assert "password" not in resp.json()
    assert "password_hash" not in resp.json()


def test_me_rejects_invalid_token(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer faketoken"})
    assert resp.status_code == 401


def test_me_rejects_missing_token(client):
    assert client.get("/auth/me").status_code == 401
