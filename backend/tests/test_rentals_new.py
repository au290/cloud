def test_duplicate_subscription_returns_400(client, seeded_packages, auth_headers):
    pkg_id = seeded_packages[0].id
    client.post(f"/rentals/{pkg_id}", headers=auth_headers)
    resp = client.post(f"/rentals/{pkg_id}", headers=auth_headers)
    assert resp.status_code == 400
    assert "already" in resp.json()["detail"].lower()


def test_can_rerent_after_release(client, seeded_packages, auth_headers):
    pkg_id = seeded_packages[0].id
    rent = client.post(f"/rentals/{pkg_id}", headers=auth_headers)
    client.delete(f"/rentals/{rent.json()['id']}", headers=auth_headers)
    resp = client.post(f"/rentals/{pkg_id}", headers=auth_headers)
    assert resp.status_code == 201


def test_compute_rent_provisions_ssm_instance(client, seeded_packages, auth_headers, mock_ministack):
    compute_pkg = seeded_packages[0]  # Basic Compute
    resp = client.post(f"/rentals/{compute_pkg.id}", headers=auth_headers)
    assert resp.status_code == 201
    mock_ministack["ssm"].put_parameter.assert_called_once()


def test_rental_logs_returns_user_history(client, seeded_packages, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    client.post(f"/rentals/{seeded_packages[1].id}", headers=auth_headers)
    resp = client.get("/rentals/logs", headers=auth_headers)
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) == 2
    assert all("action" in l for l in logs)
    assert all("package" in l for l in logs)
    assert all(l["action"] == "rent" for l in logs)


def test_rental_logs_requires_auth(client):
    resp = client.get("/rentals/logs")
    assert resp.status_code == 401


def test_rental_logs_only_shows_own_logs(client, seeded_packages, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    client.post("/auth/register", json={
        "full_name": "Other", "email": "other@example.com", "password": "pass123"
    })
    login = client.post("/auth/login", data={"username": "other@example.com", "password": "pass123"})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.post(f"/rentals/{seeded_packages[1].id}", headers=other_headers)

    resp = client.get("/rentals/logs", headers=auth_headers)
    assert len(resp.json()) == 1
