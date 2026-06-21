def test_credentials_returns_user_access_keys(client, auth_headers):
    resp = client.get("/auth/credentials", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert "access_key" in data[0]
    assert "secret_key" in data[0]
    assert "created_at" in data[0]


def test_credentials_access_key_matches_ministack(client, auth_headers):
    resp = client.get("/auth/credentials", headers=auth_headers)
    assert resp.json()[0]["access_key"].startswith("AKIA")


def test_credentials_requires_auth(client):
    resp = client.get("/auth/credentials")
    assert resp.status_code == 401


def test_credentials_isolated_per_user(client, registered_user, auth_headers):
    client.post("/auth/register", json={
        "full_name": "Other", "email": "other@example.com", "password": "pass123"
    })
    login = client.post("/auth/login", data={"username": "other@example.com", "password": "pass123"})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp1 = client.get("/auth/credentials", headers=auth_headers)
    resp2 = client.get("/auth/credentials", headers=other_headers)
    assert resp1.json()[0]["access_key"] != resp2.json()[0]["access_key"]
