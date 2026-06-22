def _packages(client):
    return {p["name"]: p for p in client.get("/api/packages").get_json()}


def _topup(client, admin_headers, amount=100, username="alice"):
    users = client.get("/api/admin/users", headers=admin_headers).get_json()
    uid = next(u for u in users if u["username"] == username)["id"]
    client.post(f"/api/admin/users/{uid}/credit", headers=admin_headers, json={"amount": amount})


def test_switch_package_keeps_bucket_and_quota(client, admin_headers, user_headers, fake_ms):
    pkgs = _packages(client)
    _topup(client, admin_headers)  # afford the paid upgrade
    # Upload something on the Free plan first.
    client.post("/api/objects", headers=user_headers,
                data={"file": (__import__("io").BytesIO(b"x" * 100), "a.txt")},
                content_type="multipart/form-data")

    res = client.post("/api/subscriptions", headers=user_headers,
                      json={"package_id": pkgs["Pro"]["id"]})
    assert res.status_code == 201, res.get_data(as_text=True)
    sub = res.get_json()
    assert sub["package"]["name"] == "Pro"
    # used_bytes carried across the switch.
    assert sub["used_bytes"] == 100

    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["subscription"]["package"]["name"] == "Pro"
    # Still exactly one bucket for the user.
    assert len(fake_ms.buckets) == 1


def test_subscriptions_history_lists_cancelled(client, admin_headers, user_headers):
    pkgs = _packages(client)
    _topup(client, admin_headers)
    client.post("/api/subscriptions", headers=user_headers, json={"package_id": pkgs["Pro"]["id"]})
    subs = client.get("/api/subscriptions", headers=user_headers).get_json()
    statuses = sorted(s["status"] for s in subs)
    assert "active" in statuses and "cancelled" in statuses


def test_subscribe_unknown_package(client, user_headers):
    res = client.post("/api/subscriptions", headers=user_headers, json={"package_id": 9999})
    assert res.status_code == 404
