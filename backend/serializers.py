"""Plain dict serializers — Flask returns JSON manually (no pydantic)."""


def _iso(dt):
    return dt.isoformat() if dt else None


def user_dict(u):
    return {
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "status": u.status.value,
        "is_admin": u.is_admin,
        "credits": float(u.credits or 0),
        "created_at": _iso(u.created_at),
    }


def package_dict(p):
    return {
        "id": p.id,
        "name": p.name,
        "quota_bytes": p.quota_bytes,
        "max_buckets": p.max_buckets,
        "price": float(p.price),
        "description": p.description,
    }


def subscription_dict(s):
    return {
        "id": s.id,
        "status": s.status.value,
        "used_bytes": s.used_bytes,
        "quota_bytes": s.quota_bytes,
        "quota_remaining": s.quota_remaining,
        "started_at": _iso(s.started_at),
        "expires_at": _iso(s.expires_at),
        "package": package_dict(s.package) if s.package else None,
    }


def bucket_dict(b):
    return {
        "id": b.id,
        "name": b.name,
        "region": b.region,
        "created_at": _iso(b.created_at),
    }


def credential_dict(c, secret=None):
    """secret is included only at creation time (shown once)."""
    out = {
        "id": c.id,
        "access_key_id": c.access_key_id,
        "status": c.status.value,
        "created_at": _iso(c.created_at),
    }
    if secret is not None:
        out["secret_key"] = secret
    return out


def object_dict(o):
    return {
        "id": o.id,
        "object_key": o.object_key,
        "size_bytes": o.size_bytes,
        "content_type": o.content_type,
        "uploaded_at": _iso(o.uploaded_at),
    }


def log_dict(l):
    return {
        "id": l.id,
        "action": l.action.value,
        "detail": l.detail,
        "bytes": l.bytes,
        "created_at": _iso(l.created_at),
    }
