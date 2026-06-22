def test_packages_seeded_at_least_three(client):
    res = client.get("/api/packages")
    assert res.status_code == 200
    pkgs = res.get_json()
    assert len(pkgs) >= 3
    names = {p["name"] for p in pkgs}
    assert {"Free", "Basic", "Pro"} <= names
    for p in pkgs:
        assert p["quota_bytes"] > 0
