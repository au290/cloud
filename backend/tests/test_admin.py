def test_admin_stats_blocked_for_regular_user(client, auth_headers):
    resp = client.get("/admin/stats", headers=auth_headers)
    assert resp.status_code == 403


def test_admin_stats_blocked_without_auth(client):
    resp = client.get("/admin/stats")
    assert resp.status_code == 401


def test_admin_stats_returns_counts(client, seeded_packages, admin_headers, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    resp = client.get("/admin/stats", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_users"] == 1         # regular user only (admin excluded)
    assert data["active_subscriptions"] == 1
    assert data["total_logs"] == 1
    assert "total_buckets" in data


def test_admin_users_blocked_for_regular_user(client, auth_headers):
    assert client.get("/admin/users", headers=auth_headers).status_code == 403


def test_admin_users_lists_all_with_subscription_counts(client, seeded_packages, admin_headers, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    client.post(f"/rentals/{seeded_packages[1].id}", headers=auth_headers)
    resp = client.get("/admin/users", headers=admin_headers)
    assert resp.status_code == 200
    users = resp.json()
    regular = next(u for u in users if not u["is_admin"])
    assert regular["active_subscriptions"] == 2
    assert regular["email"] == "test@example.com"


def test_admin_users_excludes_no_one_but_marks_admin(client, admin_headers, auth_headers):
    resp = client.get("/admin/users", headers=admin_headers)
    emails = [u["email"] for u in resp.json()]
    assert "admin@example.com" in emails
    assert "test@example.com" in emails
    admin_entry = next(u for u in resp.json() if u["email"] == "admin@example.com")
    assert admin_entry["is_admin"] is True


def test_admin_logs_blocked_for_regular_user(client, auth_headers):
    assert client.get("/admin/logs", headers=auth_headers).status_code == 403


def test_admin_logs_shows_all_users_activity(client, seeded_packages, admin_headers, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    resp = client.get("/admin/logs", headers=admin_headers)
    assert resp.status_code == 200
    logs = resp.json()
    assert len(logs) == 1
    assert logs[0]["action"] == "rent"
    assert logs[0]["user"]["email"] == "test@example.com"
    assert logs[0]["package"]["name"] == "Basic Compute"


def test_admin_logs_ordered_newest_first(client, seeded_packages, admin_headers, auth_headers):
    client.post(f"/rentals/{seeded_packages[0].id}", headers=auth_headers)
    client.post(f"/rentals/{seeded_packages[1].id}", headers=auth_headers)
    logs = client.get("/admin/logs", headers=admin_headers).json()
    assert logs[0]["package"]["name"] == "Basic Storage"  # most recent first
