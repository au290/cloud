def test_provisioning_actions_logged(client, user_headers):
    logs = client.get("/api/logs", headers=user_headers).get_json()
    actions = {l["action"] for l in logs}
    assert {"register", "subscribe", "bucket_created", "key_generated"} <= actions


def test_logs_require_auth(client):
    assert client.get("/api/logs").status_code == 401
