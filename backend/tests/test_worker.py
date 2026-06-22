def test_worker_reconciles_used_bytes_after_direct_access(client, user_headers, fake_ms):
    """A power user writes straight to the bucket, bypassing the API; the worker
    must recompute used_bytes from real bucket contents (skill §3 'Accurate')."""
    from database import db_session
    from models import Subscription, SubStatus

    sub = db_session.query(Subscription).filter(Subscription.status == SubStatus.active).first()
    assert sub.used_bytes == 0

    bucket = client.get("/api/me", headers=user_headers).get_json()["bucket"]["name"]
    # Simulate direct S3 access that the API never saw.
    fake_ms.put_object(bucket, "direct.bin", b"x" * 4096)

    import worker
    updated = worker.reconcile_once()
    assert updated == 1

    db_session.expire_all()
    sub = db_session.query(Subscription).filter(Subscription.status == SubStatus.active).first()
    assert sub.used_bytes == 4096

    # Object metadata mirror was synced too, so the file manager shows it.
    objs = client.get("/api/objects", headers=user_headers).get_json()
    assert any(o["object_key"] == "direct.bin" for o in objs)
