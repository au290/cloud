"""Quota reconciliation worker (skill §2 Job, §3 "Accurate" usage).

Power users hit MiniStack directly with their own keys, bypassing the API — so the
fast used_bytes counter drifts. This worker periodically recomputes real usage from
each bucket (list_objects_v2 → Size) and writes it back, keeping quota accurate.

Run standalone:
    python worker.py            # loops every QUOTA_RECALC_INTERVAL seconds
    python worker.py --once     # single reconciliation pass (used by tests/cron)
"""
import logging
import os
import sys
import time

from database import SessionLocal
from models import Subscription, Bucket, StoredObject, SubStatus
import ministack_client as ms

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] worker: %(message)s")
log = logging.getLogger("iaas.worker")

INTERVAL = int(os.getenv("QUOTA_RECALC_INTERVAL", "300"))


def reconcile_once() -> int:
    """Recompute used_bytes for every active subscription. Returns subs updated."""
    db = SessionLocal()
    updated = 0
    try:
        subs = db.query(Subscription).filter(Subscription.status == SubStatus.active).all()
        for sub in subs:
            bucket = db.query(Bucket).filter(Bucket.user_id == sub.user_id).first()
            if not bucket:
                continue
            try:
                # Re-create the bucket if MiniStack lost it (idempotent), then list.
                ms.create_bucket(bucket.name, bucket.region)
                objects = ms.list_objects(bucket.name)
            except Exception as e:
                log.warning("Could not list %s: %s", bucket.name, e)
                continue

            real_total = sum(o["size"] for o in objects)
            if real_total != sub.used_bytes:
                log.info("sub %s used_bytes %s -> %s", sub.id, sub.used_bytes, real_total)
                sub.used_bytes = real_total
                updated += 1

            # Refresh the object metadata mirror so the file manager stays in sync.
            _sync_object_metadata(db, bucket, objects)
        db.commit()
    finally:
        db.close()
    return updated


def _sync_object_metadata(db, bucket, objects):
    live = {o["key"]: o["size"] for o in objects}
    existing = {
        o.object_key: o
        for o in db.query(StoredObject).filter(StoredObject.bucket_id == bucket.id).all()
    }
    for key, size in live.items():
        if key in existing:
            existing[key].size_bytes = size
        else:
            db.add(StoredObject(bucket_id=bucket.id, object_key=key, size_bytes=size))
    for key, obj in existing.items():
        if key not in live:
            db.delete(obj)


def main():
    if "--once" in sys.argv:
        n = reconcile_once()
        log.info("Reconciliation pass complete (%s subscriptions updated).", n)
        return
    log.info("Worker started; reconciling every %s seconds.", INTERVAL)
    while True:
        try:
            reconcile_once()
        except Exception as e:
            log.error("Reconciliation error: %s", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
