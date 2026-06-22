"""Buckets survive a MiniStack wipe: the app re-creates DB-known buckets and uploads
keep working even after MiniStack loses its in-memory state."""
import io


def test_reconcile_recreates_missing_buckets(client, user_headers, fake_ms):
    bucket = client.get("/api/me", headers=user_headers).get_json()["bucket"]["name"]
    assert bucket in fake_ms.buckets

    # Simulate a MiniStack restart without persistence: everything gone.
    fake_ms.buckets.clear()
    assert bucket not in fake_ms.buckets

    from provisioning import reconcile_buckets
    ensured = reconcile_buckets()
    assert ensured >= 1
    assert bucket in fake_ms.buckets  # back again


def test_upload_recovers_after_bucket_wipe(client, user_headers, fake_ms):
    # Wipe MiniStack, then upload — the handler should recreate the bucket and succeed.
    fake_ms.buckets.clear()
    res = client.post(
        "/api/objects", headers=user_headers,
        data={"file": (io.BytesIO(b"recovered"), "after-wipe.txt")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 201, res.get_data(as_text=True)
    listed = client.get("/api/objects", headers=user_headers).get_json()
    assert any(o["object_key"] == "after-wipe.txt" for o in listed)
