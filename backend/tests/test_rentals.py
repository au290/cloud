def test_rent_package_creates_active_subscription(client, seeded_packages, auth_headers):
    resp = client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "active"
    assert data["package"]["name"] == "Basic Compute"


def test_rent_nonexistent_package_returns_404(client, auth_headers):
    resp = client.post("/rentals/9999", headers=auth_headers)
    assert resp.status_code == 404


def test_rent_requires_auth(client, seeded_packages):
    resp = client.post(f"/rentals/{seeded_packages[0].id}")
    assert resp.status_code == 401


def test_renting_storage_creates_s3_bucket(client, seeded_packages, auth_headers, mock_ministack):
    storage_pkg = seeded_packages[1]  # Basic Storage
    resp = client.post(f"/rentals/{storage_pkg.id}", headers=auth_headers)
    assert resp.status_code == 201
    mock_ministack["s3"].create_bucket.assert_called_once()


def test_release_subscription(client, seeded_packages, auth_headers):
    rent_resp = client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    sub_id = rent_resp.json()["id"]

    release_resp = client.delete(f"/rentals/{sub_id}", headers=auth_headers)
    assert release_resp.status_code == 200
    assert release_resp.json()["status"] == "cancelled"


def test_cannot_release_another_users_subscription(client, seeded_packages, auth_headers):
    rent_resp = client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    sub_id = rent_resp.json()["id"]

    # second user tries to release it
    client.post("/auth/register", json={
        "full_name": "Other User", "email": "other@example.com", "password": "pass123"
    })
    login = client.post("/auth/login", data={"username": "other@example.com", "password": "pass123"})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.delete(f"/rentals/{sub_id}", headers=other_headers)
    assert resp.status_code == 404
