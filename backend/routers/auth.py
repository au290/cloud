import logging

from flask import Blueprint, request, jsonify, g
from sqlalchemy.exc import IntegrityError

from database import db_session
from models import User, Package, Subscription, Bucket, SubStatus, LogAction
from security import hash_password, verify_password, create_access_token, login_required
from serializers import user_dict, subscription_dict, bucket_dict
from provisioning import provision_new_user, log_action

log = logging.getLogger("iaas.auth")
bp = Blueprint("auth", __name__, url_prefix="/api")


@bp.post("/register")
def register():
    """Create the user, then run the full provisioning flow (skill §5).

    The plaintext secret key is returned exactly once, here.
    """
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not username or not email or not password:
        return jsonify({"detail": "username, email and password are required"}), 400

    user = User(username=username, email=email, password_hash=hash_password(password))
    db_session.add(user)
    try:
        db_session.flush()
    except IntegrityError:
        db_session.rollback()
        return jsonify({"detail": "Username or email already registered"}), 400

    log_action(user.id, LogAction.register, detail=email)

    # Default everyone onto the cheapest package so they get a bucket + quota immediately.
    package = (
        db_session.query(Package).order_by(Package.price.asc(), Package.id.asc()).first()
    )
    secret = None
    if package:
        try:
            secret = provision_new_user(user, package)
        except Exception as e:
            log.error("Provisioning failed for user %s: %s", user.id, e)

    db_session.commit()

    sub = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == SubStatus.active)
        .first()
    )
    bucket = db_session.query(Bucket).filter(Bucket.user_id == user.id).first()
    return jsonify({
        "user": user_dict(user),
        "subscription": subscription_dict(sub) if sub else None,
        "bucket": bucket_dict(bucket) if bucket else None,
        # shown once — never retrievable again
        "secret_key": secret,
        "access_key_id": user.credentials[0].access_key_id if user.credentials else None,
    }), 201


@bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    user = db_session.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.password_hash):
        return jsonify({"detail": "Invalid email or password"}), 401
    return jsonify({
        "access_token": create_access_token(user.id),
        "token_type": "bearer",
        "is_admin": user.is_admin,
    })


@bp.get("/me")
@login_required
def me():
    user = g.current_user
    sub = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == SubStatus.active)
        .first()
    )
    bucket = db_session.query(Bucket).filter(Bucket.user_id == user.id).first()
    return jsonify({
        "user": user_dict(user),
        "subscription": subscription_dict(sub) if sub else None,
        "bucket": bucket_dict(bucket) if bucket else None,
    })
