"""Proves the platform really validates bucket/quota size, using a 100 MB limit.

Creates a package whose quota is exactly 100 MB, puts the user on it, and checks the
boundary: a file that fits is stored, a file that would exceed 100 MB is rejected
with HTTP 413 *before* anything is written to (fake) MiniStack.
"""
import io

MB = 1024 * 1024


def _make_100mb_package_and_subscribe(client, admin_headers, user_headers):
    res = client.post("/api/admin/packages", headers=admin_headers, json={
        "name": "Test100MB",
        "quota_bytes": 100 * MB,
        "max_buckets": 1,
        "price": 0,
        "description": "100 MB hard limit",
    })
    assert res.status_code == 201, res.get_data(as_text=True)
    pkg_id = res.get_json()["id"]

    res = client.post("/api/subscriptions", headers=user_headers, json={"package_id": pkg_id})
    assert res.status_code == 201
    assert res.get_json()["quota_bytes"] == 100 * MB
    return pkg_id


def _upload(client, headers, name, data: bytes):
    return client.post(
        "/api/objects", headers=headers,
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_100mb_limit_accepts_under_and_rejects_over(client, admin_headers, user_headers, fake_ms):
    _make_100mb_package_and_subscribe(client, admin_headers, user_headers)
    bucket = client.get("/api/me", headers=user_headers).get_json()["bucket"]["name"]

    # 60 MB fits comfortably under 100 MB.
    ok = _upload(client, user_headers, "part1.bin", b"\0" * (60 * MB))
    assert ok.status_code == 201
    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["subscription"]["used_bytes"] == 60 * MB

    # Another 60 MB would total 120 MB > 100 MB → rejected, nothing written.
    rejected = _upload(client, user_headers, "part2.bin", b"\0" * (60 * MB))
    assert rejected.status_code == 413
    body = rejected.get_json()
    assert "Quota exceeded" in body["detail"]
    assert body["remaining_bytes"] == 40 * MB
    assert "part2.bin" not in fake_ms.buckets.get(bucket, {})

    # used_bytes unchanged, and a quota_exceeded event was logged.
    me2 = client.get("/api/me", headers=user_headers).get_json()
    assert me2["subscription"]["used_bytes"] == 60 * MB
    logs = client.get("/api/logs", headers=user_headers).get_json()
    assert any(l["action"] == "quota_exceeded" for l in logs)


def test_single_file_just_over_100mb_rejected(client, admin_headers, user_headers, fake_ms):
    _make_100mb_package_and_subscribe(client, admin_headers, user_headers)
    over = _upload(client, user_headers, "big.bin", b"\0" * (100 * MB + 1))
    assert over.status_code == 413
    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["subscription"]["used_bytes"] == 0
