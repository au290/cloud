import logging
from decimal import Decimal

from flask import Blueprint, request, jsonify, g

from database import db_session
from models import Package, Subscription, SubStatus, LogAction
from security import login_required
from serializers import subscription_dict
from provisioning import subscribe, log_action

log = logging.getLogger("iaas.subscriptions")
bp = Blueprint("subscriptions", __name__, url_prefix="/api")


@bp.get("/subscriptions")
@login_required
def list_subscriptions():
    subs = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == g.current_user.id)
        .order_by(Subscription.id.desc())
        .all()
    )
    return jsonify([subscription_dict(s) for s in subs])


@bp.post("/subscriptions")
@login_required
def create_subscription():
    """Subscribe to / upgrade to a package, paying its price from the user's credits.

    Rules: you can only choose a package you can afford; the price is deducted on
    success. Re-selecting your current package is rejected (no double-charge).
    """
    user = g.current_user
    data = request.get_json(silent=True) or {}
    package_id = data.get("package_id")
    if not package_id:
        return jsonify({"detail": "package_id is required"}), 400

    package = db_session.query(Package).filter(Package.id == package_id).first()
    if not package:
        return jsonify({"detail": "Package not found"}), 404

    current = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == SubStatus.active)
        .first()
    )
    if current and current.package_id == package.id:
        return jsonify({"detail": "You are already on this package"}), 400

    cost = Decimal(package.price or 0)
    balance = Decimal(user.credits or 0)
    if cost > balance:
        return jsonify({
            "detail": f"Insufficient credit: {package.name} costs {float(cost):.2f}, "
                      f"your balance is {float(balance):.2f}",
            "needed": float(cost),
            "balance": float(balance),
        }), 402  # Payment Required

    try:
        sub = subscribe(user, package)
        if cost > 0:
            user.credits = balance - cost
            log_action(user.id, LogAction.payment, detail=f"{package.name} (-{float(cost):.2f})")
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        log.error("Subscribe failed for user %s: %s", user.id, e)
        return jsonify({"detail": "Could not provision subscription"}), 502

    return jsonify({**subscription_dict(sub), "balance": float(user.credits or 0)}), 201
