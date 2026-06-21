def test_dashboard_shows_user_info(client, auth_headers):
    resp = client.get("/dashboard", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "test@example.com"


def test_dashboard_empty_when_no_subscriptions(client, auth_headers):
    resp = client.get("/dashboard", headers=auth_headers)
    assert resp.json()["subscriptions"] == []


def test_dashboard_shows_active_subscription_after_rent(client, seeded_packages, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    resp = client.get("/dashboard", headers=auth_headers)
    subs = resp.json()["subscriptions"]
    assert len(subs) == 1
    assert subs[0]["status"] == "active"
    assert subs[0]["package"]["name"] == "Basic Compute"
    assert subs[0]["package"]["quota_value"] == 2
    assert subs[0]["package"]["quota_unit"] == "vCPU"


def test_dashboard_hides_cancelled_subscription(client, seeded_packages, auth_headers):
    rent = client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    client.delete(f"/rentals/{rent.json()['id']}", headers=auth_headers)
    resp = client.get("/dashboard", headers=auth_headers)
    assert resp.json()["subscriptions"] == []


def test_dashboard_requires_auth(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 401
