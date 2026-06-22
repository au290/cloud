"""Admin CRUD + moderation + per-user log filtering."""
MB = 1024 * 1024


def test_package_crud(client, admin_headers):
    # create
    res = client.post("/api/admin/packages", headers=admin_headers,
                      json={"name": "Team", "quota_bytes": 10 * MB, "max_buckets": 2, "price": 9.5})
    assert res.status_code == 201
    pid = res.get_json()["id"]

    # duplicate name rejected
    dup = client.post("/api/admin/packages", headers=admin_headers,
                      json={"name": "Team", "quota_bytes": 1})
    assert dup.status_code == 409

    # update
    upd = client.put(f"/api/admin/packages/{pid}", headers=admin_headers, json={"quota_bytes": 20 * MB})
    assert upd.status_code == 200 and upd.get_json()["quota_bytes"] == 20 * MB

    # delete (unused package)
    assert client.delete(f"/api/admin/packages/{pid}", headers=admin_headers).status_code == 200


def test_cannot_delete_package_in_use(client, admin_headers, user_headers):
    # Free package (id from seed) is in use by the registered user's subscription.
    pkgs = client.get("/api/admin/packages", headers=admin_headers).get_json()
    free = next(p for p in pkgs if p["name"] == "Free")
    res = client.delete(f"/api/admin/packages/{free['id']}", headers=admin_headers)
    assert res.status_code == 409


def test_suspend_blocks_login_then_activate_restores(client, admin_headers, user_headers):
    users = client.get("/api/admin/users", headers=admin_headers).get_json()
    alice = next(u for u in users if u["username"] == "alice")

    assert client.post(f"/api/admin/users/{alice['id']}/suspend", headers=admin_headers).status_code == 200
    # A suspended user's token is rejected.
    assert client.get("/api/me", headers=user_headers).status_code == 403

    assert client.post(f"/api/admin/users/{alice['id']}/activate", headers=admin_headers).status_code == 200
    assert client.get("/api/me", headers=user_headers).status_code == 200


def test_delete_user_cascades(client, admin_headers, user_headers):
    users = client.get("/api/admin/users", headers=admin_headers).get_json()
    alice = next(u for u in users if u["username"] == "alice")
    assert client.delete(f"/api/admin/users/{alice['id']}", headers=admin_headers).status_code == 200
    # Gone from the listing and their token no longer resolves.
    remaining = client.get("/api/admin/users", headers=admin_headers).get_json()
    assert all(u["username"] != "alice" for u in remaining)
    assert client.get("/api/me", headers=user_headers).status_code == 401


def test_admin_cannot_be_deleted(client, admin_headers):
    users = client.get("/api/admin/users", headers=admin_headers).get_json()
    admin = next(u for u in users if u["is_admin"])
    assert client.delete(f"/api/admin/users/{admin['id']}", headers=admin_headers).status_code == 400


def test_logs_filter_by_user(client, admin_headers, user_headers):
    users = client.get("/api/admin/users", headers=admin_headers).get_json()
    alice = next(u for u in users if u["username"] == "alice")

    filtered = client.get(f"/api/admin/logs?user_id={alice['id']}", headers=admin_headers).get_json()
    assert filtered and all(l["user"]["id"] == alice["id"] for l in filtered)

    per_user = client.get(f"/api/admin/users/{alice['id']}/logs", headers=admin_headers).get_json()
    assert all(l["user"]["id"] == alice["id"] for l in per_user)
