def test_quota_returns_active_subscriptions(client, seeded_packages, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    resp = client.get("/dashboard/quota", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["package"]["quota_value"] == 2
    assert data[0]["package"]["quota_unit"] == "vCPU"


def test_quota_empty_when_no_active_subscriptions(client, auth_headers):
    resp = client.get("/dashboard/quota", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_quota_requires_auth(client):
    assert client.get("/dashboard/quota").status_code == 401


def test_dashboard_credentials_lists_iam_keys(client, auth_headers):
    resp = client.get("/dashboard/credentials", headers=auth_headers)
    assert resp.status_code == 200
    creds = resp.json()
    assert len(creds) == 1
    assert creds[0]["access_key"].startswith("AKIA")
    assert "secret_key" in creds[0]


def test_dashboard_credentials_requires_auth(client):
    assert client.get("/dashboard/credentials").status_code == 401


def test_request_new_credentials_generates_additional_keys(client, auth_headers):
    resp = client.post("/dashboard/credentials", headers=auth_headers)
    assert resp.status_code == 201
    assert "access_key" in resp.json()
    assert "secret_key" in resp.json()

    all_creds = client.get("/dashboard/credentials", headers=auth_headers)
    assert len(all_creds.json()) == 2


def test_request_credentials_requires_auth(client):
    assert client.post("/dashboard/credentials").status_code == 401
