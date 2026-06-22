def test_public_config(client):
    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.get_json()
    assert "ministack_endpoint" in body and "region" in body
