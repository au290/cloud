import io


def _upload(client, headers, name, data: bytes):
    return client.post(
        "/api/objects", headers=headers,
        data={"file": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_upload_list_download_delete(client, user_headers, fake_ms):
    res = _upload(client, user_headers, "hello.txt", b"hi there")
    assert res.status_code == 201, res.get_data(as_text=True)
    assert res.get_json()["size_bytes"] == 8

    listed = client.get("/api/objects", headers=user_headers).get_json()
    assert any(o["object_key"] == "hello.txt" for o in listed)

    # used_bytes advanced on the active subscription.
    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["subscription"]["used_bytes"] == 8

    # Presigned download URL.
    dl = client.get("/api/objects/hello.txt?presigned=1", headers=user_headers)
    assert dl.status_code == 200 and "url" in dl.get_json()

    # Delete frees the quota and removes the object.
    d = client.delete("/api/objects/hello.txt", headers=user_headers)
    assert d.status_code == 200
    me2 = client.get("/api/me", headers=user_headers).get_json()
    assert me2["subscription"]["used_bytes"] == 0
    assert client.get("/api/objects", headers=user_headers).get_json() == []


def test_quota_enforced_before_put(client, user_headers, fake_ms):
    # Free plan is 1 GB; craft a payload just over it would be huge, so shrink quota instead.
    from database import db_session
    from models import Subscription, SubStatus
    sub = db_session.query(Subscription).filter(Subscription.status == SubStatus.active).first()
    sub.used_bytes = sub.package.quota_bytes - 5  # only 5 bytes left
    db_session.commit()

    bucket = client.get("/api/me", headers=user_headers).get_json()["bucket"]["name"]
    res = _upload(client, user_headers, "big.bin", b"0123456789")  # 10 bytes
    assert res.status_code == 413
    assert "Quota exceeded" in res.get_json()["detail"]

    # Nothing was written to storage, and a quota_exceeded log exists.
    assert "big.bin" not in fake_ms.buckets.get(bucket, {})
    logs = client.get("/api/logs", headers=user_headers).get_json()
    assert any(l["action"] == "quota_exceeded" for l in logs)


def test_overwrite_adjusts_used_bytes(client, user_headers):
    _upload(client, user_headers, "f.txt", b"aaaa")       # 4 bytes
    _upload(client, user_headers, "f.txt", b"bbbbbbbb")    # 8 bytes (overwrite)
    me = client.get("/api/me", headers=user_headers).get_json()
    assert me["subscription"]["used_bytes"] == 8
