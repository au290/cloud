"""File-manager endpoints — the UI layer over the user's S3 bucket.

All storage actions go through here so quota is enforced and activity is logged
(skill §3 "enforce quota in the application").
"""
import io
import os
import logging

from flask import Blueprint, request, jsonify, g, Response

from database import db_session
from models import Bucket, Subscription, StoredObject, SubStatus, LogAction
import ministack_client as ms
from security import login_required
from serializers import object_dict
from provisioning import log_action

log = logging.getLogger("iaas.objects")
bp = Blueprint("objects", __name__, url_prefix="/api")


def _active_context(user):
    """Return (subscription, bucket) for the user's active subscription, or (None, None)."""
    sub = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == SubStatus.active)
        .first()
    )
    bucket = db_session.query(Bucket).filter(Bucket.user_id == user.id).first()
    return sub, bucket


@bp.get("/objects")
@login_required
def list_objects():
    _, bucket = _active_context(g.current_user)
    if not bucket:
        return jsonify([])
    rows = (
        db_session.query(StoredObject)
        .filter(StoredObject.bucket_id == bucket.id)
        .order_by(StoredObject.uploaded_at.desc())
        .all()
    )
    return jsonify([object_dict(o) for o in rows])


@bp.post("/objects")
@login_required
def upload_object():
    user = g.current_user
    sub, bucket = _active_context(user)
    if not sub or not bucket:
        return jsonify({"detail": "No active subscription / bucket"}), 400

    file = request.files.get("file")
    if not file:
        return jsonify({"detail": "No file provided (multipart field 'file')"}), 400

    key = (request.form.get("key") or file.filename or "").strip().lstrip("/")
    if not key:
        return jsonify({"detail": "Object key is required"}), 400

    # Measure the size from the stream without reading it all into memory, so the
    # quota check works even for multi-hundred-MB files (Werkzeug spools the body
    # to a temp file). We then hand the same stream to boto3's multipart uploader.
    stream = file.stream
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)

    # Quota enforcement (skill §3): reject before the put if it would exceed the limit.
    quota = sub.quota_bytes or 0
    if sub.used_bytes + size > quota:
        log_action(user.id, LogAction.quota_exceeded, detail=key, num_bytes=size)
        db_session.commit()
        remaining = max(quota - sub.used_bytes, 0)
        return jsonify({
            "detail": f"Quota exceeded: file is {size} bytes, only {remaining} bytes remaining",
            "remaining_bytes": remaining,
        }), 413

    content_type = file.mimetype or "application/octet-stream"
    try:
        ms.upload_fileobj(bucket.name, key, stream, content_type)
    except Exception as e:
        # The bucket may have been lost on a MiniStack restart — recreate and retry once.
        log.warning("upload failed for %s/%s (%s); recreating bucket and retrying", bucket.name, key, e)
        try:
            ms.create_bucket(bucket.name, bucket.region)
            stream.seek(0)
            ms.upload_fileobj(bucket.name, key, stream, content_type)
        except Exception as e2:
            log.error("upload retry failed for %s/%s: %s", bucket.name, key, e2)
            return jsonify({"detail": "Upload to storage backend failed"}), 502

    # Upsert object metadata and adjust the fast usage counter.
    existing = (
        db_session.query(StoredObject)
        .filter(StoredObject.bucket_id == bucket.id, StoredObject.object_key == key)
        .first()
    )
    if existing:
        sub.used_bytes += size - existing.size_bytes
        existing.size_bytes = size
        existing.content_type = content_type
        obj = existing
    else:
        sub.used_bytes += size
        obj = StoredObject(bucket_id=bucket.id, object_key=key,
                           size_bytes=size, content_type=content_type)
        db_session.add(obj)

    log_action(user.id, LogAction.upload, detail=key, num_bytes=size)
    db_session.commit()
    return jsonify(object_dict(obj)), 201


@bp.get("/objects/<path:key>")
@login_required
def download_object(key):
    user = g.current_user
    _, bucket = _active_context(user)
    if not bucket:
        return jsonify({"detail": "No bucket"}), 404

    # ?presigned=1 → hand back a direct MiniStack URL instead of streaming through the API.
    if request.args.get("presigned"):
        try:
            url = ms.presigned_url(bucket.name, key)
        except Exception as e:
            log.error("presign failed for %s/%s: %s", bucket.name, key, e)
            return jsonify({"detail": "Could not create download URL"}), 502
        log_action(user.id, LogAction.download, detail=key)
        db_session.commit()
        return jsonify({"url": url})

    try:
        body, content_type = ms.get_object(bucket.name, key)
    except Exception as e:
        log.error("get_object failed for %s/%s: %s", bucket.name, key, e)
        return jsonify({"detail": "Object not found"}), 404

    log_action(user.id, LogAction.download, detail=key)
    db_session.commit()
    filename = key.rsplit("/", 1)[-1]
    return Response(
        io.BytesIO(body),
        mimetype=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.delete("/objects/<path:key>")
@login_required
def delete_object(key):
    user = g.current_user
    sub, bucket = _active_context(user)
    if not bucket:
        return jsonify({"detail": "No bucket"}), 404

    try:
        ms.delete_object(bucket.name, key)
    except Exception as e:
        log.error("delete_object failed for %s/%s: %s", bucket.name, key, e)
        return jsonify({"detail": "Delete failed"}), 502

    obj = (
        db_session.query(StoredObject)
        .filter(StoredObject.bucket_id == bucket.id, StoredObject.object_key == key)
        .first()
    )
    if obj:
        if sub:
            sub.used_bytes = max(sub.used_bytes - obj.size_bytes, 0)
        db_session.delete(obj)

    log_action(user.id, LogAction.delete, detail=key)
    db_session.commit()
    return jsonify({"deleted": key})
