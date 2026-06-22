"""Credit/billing rules: credits = money, only admins top up, price gates upgrades."""


def _pkg(client, name):
    return next(p for p in client.get("/api/packages").get_json() if p["name"] == name)


def _uid(client, admin_headers, username="alice"):
    users = client.get("/api/admin/users", headers=admin_headers).get_json()
    return next(u for u in users if u["username"] == username)["id"]


def test_new_user_starts_with_zero_credits_on_free(client, user_headers):
    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["user"]["credits"] == 0
    assert me["subscription"]["package"]["name"] == "Free"  # the free tier needs no credit


def test_cannot_upgrade_without_enough_credit(client, user_headers):
    pro = _pkg(client, "Pro")
    res = client.post("/api/subscriptions", headers=user_headers, json={"package_id": pro["id"]})
    assert res.status_code == 402
    assert res.get_json()["needed"] == pro["price"]
    # unchanged: still on Free
    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["subscription"]["package"]["name"] == "Free"


def test_admin_topup_then_upgrade_deducts_price(client, admin_headers, user_headers):
    pro = _pkg(client, "Pro")
    uid = _uid(client, admin_headers)

    topup = client.post(f"/api/admin/users/{uid}/credit", headers=admin_headers, json={"amount": 30})
    assert topup.status_code == 200 and topup.get_json()["credits"] == 30

    sub = client.post("/api/subscriptions", headers=user_headers, json={"package_id": pro["id"]})
    assert sub.status_code == 201

    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["subscription"]["package"]["name"] == "Pro"
    assert me["user"]["credits"] == 30 - pro["price"]  # 30 - 25 = 5


def test_reselecting_current_package_is_rejected(client, user_headers):
    free = _pkg(client, "Free")  # user is already on Free from registration
    res = client.post("/api/subscriptions", headers=user_headers, json={"package_id": free["id"]})
    assert res.status_code == 400


def test_only_admin_can_add_credit(client, admin_headers, user_headers):
    uid = _uid(client, admin_headers)
    res = client.post(f"/api/admin/users/{uid}/credit", headers=user_headers, json={"amount": 10})
    assert res.status_code == 403


def test_credit_cannot_go_negative(client, admin_headers, user_headers):
    uid = _uid(client, admin_headers)
    res = client.post(f"/api/admin/users/{uid}/credit", headers=admin_headers, json={"amount": -5})
    assert res.status_code == 400  # balance is 0, can't deduct below zero


def test_payment_and_credit_events_logged(client, admin_headers, user_headers):
    pro = _pkg(client, "Pro")
    uid = _uid(client, admin_headers)
    client.post(f"/api/admin/users/{uid}/credit", headers=admin_headers, json={"amount": 100})
    client.post("/api/subscriptions", headers=user_headers, json={"package_id": pro["id"]})

    actions = {l["action"] for l in client.get("/api/logs", headers=user_headers).get_json()}
    assert "payment" in actions
    admin_view = client.get(f"/api/admin/users/{uid}/logs", headers=admin_headers).get_json()
    assert any(l["action"] == "credit_added" for l in admin_view)
