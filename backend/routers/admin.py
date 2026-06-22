"""Admin endpoints (extension beyond the skill's user-facing contract).

Oversight + management of users, packages, subscriptions, buckets and activity:
read-only dashboards plus CRUD on packages and moderation actions on users.
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request, g

from sqlalchemy import func

from database import db_session
from models import (
    User, Package, Subscription, Bucket, Credential, StoredObject,
    ActivityLog, SubStatus, UserStatus, LogAction,
)
from security import admin_required
from serializers import log_dict, package_dict
from provisioning import log_action

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


def _log_with_user(l):
    d = log_dict(l)
    d["user"] = (
        {"id": l.user.id, "username": l.user.username, "email": l.user.email}
        if l.user else None
    )
    return d


# --- dashboards -------------------------------------------------------------
@bp.get("/stats")
@admin_required
def stats():
    total_users = db_session.query(User).filter(User.is_admin.is_(False)).count()
    active_subs = db_session.query(Subscription).filter(Subscription.status == SubStatus.active).count()
    total_logs = db_session.query(ActivityLog).count()
    total_buckets = db_session.query(Bucket).count()
    used = db_session.query(func.coalesce(func.sum(Subscription.used_bytes), 0)).filter(
        Subscription.status == SubStatus.active
    ).scalar()
    return jsonify({
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "total_logs": total_logs,
        "total_buckets": total_buckets,
        "total_used_bytes": int(used or 0),
    })


@bp.get("/users")
@admin_required
def users():
    rows = db_session.query(User).order_by(User.created_at.desc()).all()
    counts = dict(
        db_session.query(Subscription.user_id, func.count(Subscription.id))
        .filter(Subscription.status == SubStatus.active)
        .group_by(Subscription.user_id)
        .all()
    )
    out = []
    for u in rows:
        active = next((s for s in u.subscriptions if s.status == SubStatus.active), None)
        out.append({
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "status": u.status.value,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "active_subscriptions": counts.get(u.id, 0),
            "used_bytes": active.used_bytes if active else 0,
            "credits": float(u.credits or 0),
            "package": package_dict(active.package) if active and active.package else None,
        })
    return jsonify(out)


@bp.post("/users/<int:user_id>/credit")
@admin_required
def add_credit(user_id):
    """Top up (or correct) a user's credit balance. Admin-only."""
    data = request.get_json(silent=True) or {}
    raw = data.get("amount")
    if raw is None:
        return jsonify({"detail": "amount is required"}), 400
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return jsonify({"detail": "amount must be a number"}), 400
    if amount == 0:
        return jsonify({"detail": "amount must be non-zero"}), 400

    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"detail": "User not found"}), 404

    new_balance = Decimal(user.credits or 0) + amount
    if new_balance < 0:
        return jsonify({"detail": "Adjustment would make the balance negative"}), 400

    user.credits = new_balance
    log_action(user.id, LogAction.credit_added, detail=f"{float(amount):+.2f}")
    db_session.commit()
    return jsonify({"id": user.id, "credits": float(user.credits)})


# --- activity logs (filterable by user) -------------------------------------
@bp.get("/logs")
@admin_required
def logs():
    """All activity, newest first. Filter to one user with ?user_id=, page with
    ?before_id= (keyset pagination) so it scales past many users/rows."""
    limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
    user_id = request.args.get("user_id", type=int)
    before_id = request.args.get("before_id", type=int)

    q = db_session.query(ActivityLog)
    if user_id:
        q = q.filter(ActivityLog.user_id == user_id)
    if before_id:
        q = q.filter(ActivityLog.id < before_id)
    rows = q.order_by(ActivityLog.id.desc()).limit(limit).all()
    return jsonify([_log_with_user(l) for l in rows])


@bp.get("/users/<int:user_id>/logs")
@admin_required
def user_logs(user_id):
    limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
    rows = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.user_id == user_id)
        .order_by(ActivityLog.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify([_log_with_user(l) for l in rows])


# --- package CRUD -----------------------------------------------------------
@bp.get("/packages")
@admin_required
def list_packages():
    rows = db_session.query(Package).order_by(Package.price.asc(), Package.id.asc()).all()
    return jsonify([package_dict(p) for p in rows])


def _package_payload():
    data = request.get_json(silent=True) or {}
    return data, (data.get("name") or "").strip()


@bp.post("/packages")
@admin_required
def create_package():
    data, name = _package_payload()
    if not name or data.get("quota_bytes") is None:
        return jsonify({"detail": "name and quota_bytes are required"}), 400
    if db_session.query(Package).filter(Package.name == name).first():
        return jsonify({"detail": "A package with that name already exists"}), 409
    pkg = Package(
        name=name,
        quota_bytes=int(data["quota_bytes"]),
        max_buckets=int(data.get("max_buckets", 1)),
        price=data.get("price", 0),
        description=data.get("description"),
    )
    db_session.add(pkg)
    db_session.commit()
    return jsonify(package_dict(pkg)), 201


@bp.put("/packages/<int:package_id>")
@admin_required
def update_package(package_id):
    pkg = db_session.query(Package).filter(Package.id == package_id).first()
    if not pkg:
        return jsonify({"detail": "Package not found"}), 404
    data = request.get_json(silent=True) or {}
    if "name" in data and data["name"].strip():
        pkg.name = data["name"].strip()
    if data.get("quota_bytes") is not None:
        pkg.quota_bytes = int(data["quota_bytes"])
    if data.get("max_buckets") is not None:
        pkg.max_buckets = int(data["max_buckets"])
    if data.get("price") is not None:
        pkg.price = data["price"]
    if "description" in data:
        pkg.description = data["description"]
    db_session.commit()
    return jsonify(package_dict(pkg))


@bp.delete("/packages/<int:package_id>")
@admin_required
def delete_package(package_id):
    pkg = db_session.query(Package).filter(Package.id == package_id).first()
    if not pkg:
        return jsonify({"detail": "Package not found"}), 404
    in_use = db_session.query(Subscription).filter(Subscription.package_id == package_id).count()
    if in_use:
        return jsonify({"detail": f"Package is in use by {in_use} subscription(s); cannot delete"}), 409
    db_session.delete(pkg)
    db_session.commit()
    return jsonify({"deleted": package_id})


# --- user moderation --------------------------------------------------------
@bp.post("/users/<int:user_id>/suspend")
@admin_required
def suspend_user(user_id):
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"detail": "User not found"}), 404
    if user.is_admin:
        return jsonify({"detail": "Cannot suspend an admin"}), 400
    user.status = UserStatus.suspended
    db_session.commit()
    return jsonify({"id": user.id, "status": user.status.value})


@bp.post("/users/<int:user_id>/activate")
@admin_required
def activate_user(user_id):
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"detail": "User not found"}), 404
    user.status = UserStatus.active
    db_session.commit()
    return jsonify({"id": user.id, "status": user.status.value})


@bp.delete("/users/<int:user_id>")
@admin_required
def delete_user(user_id):
    """Hard-delete a user and everything they own (cascading manually, since the
    FKs have no ON DELETE CASCADE). The MiniStack bucket itself is left in place."""
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"detail": "User not found"}), 404
    if user.is_admin:
        return jsonify({"detail": "Cannot delete an admin account"}), 400
    if g.current_user.id == user_id:
        return jsonify({"detail": "Cannot delete your own account"}), 400

    bucket_ids = [b.id for b in db_session.query(Bucket.id).filter(Bucket.user_id == user_id).all()]
    if bucket_ids:
        db_session.query(StoredObject).filter(StoredObject.bucket_id.in_(bucket_ids)).delete(synchronize_session=False)
    db_session.query(Bucket).filter(Bucket.user_id == user_id).delete(synchronize_session=False)
    db_session.query(Credential).filter(Credential.user_id == user_id).delete(synchronize_session=False)
    db_session.query(Subscription).filter(Subscription.user_id == user_id).delete(synchronize_session=False)
    db_session.query(ActivityLog).filter(ActivityLog.user_id == user_id).delete(synchronize_session=False)
    db_session.delete(user)
    db_session.commit()
    return jsonify({"deleted": user_id})
