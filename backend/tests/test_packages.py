def test_list_packages_returns_all(client, seeded_packages):
    resp = client.get("/packages")
    assert resp.status_code == 200
    assert len(resp.json()) == 3


def test_package_response_has_required_fields(client, seeded_packages):
    resp = client.get("/packages")
    pkg = resp.json()[0]
    assert "id" in pkg
    assert "name" in pkg
    assert "type" in pkg
    assert "quota_value" in pkg
    assert "quota_unit" in pkg
    assert "price" in pkg


def test_packages_are_publicly_accessible(client, seeded_packages):
    resp = client.get("/packages")
    assert resp.status_code == 200
