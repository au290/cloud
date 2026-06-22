def test_admin_stats(client, user_headers, admin_headers):
    res = client.get("/api/admin/stats", headers=admin_headers)
    assert res.status_code == 200
    s = res.get_json()
    assert s["total_users"] >= 1
    assert s["active_subscriptions"] >= 1
    assert s["total_buckets"] >= 1


def test_admin_users_and_logs(client, user_headers, admin_headers):
    users = client.get("/api/admin/users", headers=admin_headers)
    assert users.status_code == 200
    assert any(u["username"] == "alice" for u in users.get_json())

    logs = client.get("/api/admin/logs", headers=admin_headers)
    assert logs.status_code == 200


def test_admin_forbidden_for_normal_user(client, user_headers):
    assert client.get("/api/admin/stats", headers=user_headers).status_code == 403
