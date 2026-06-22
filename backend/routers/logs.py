from flask import Blueprint, jsonify, g, request

from database import db_session
from models import ActivityLog
from security import login_required
from serializers import log_dict

bp = Blueprint("logs", __name__, url_prefix="/api")


@bp.get("/logs")
@login_required
def list_logs():
    limit = min(max(request.args.get("limit", 50, type=int), 1), 200)
    rows = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.user_id == g.current_user.id)
        .order_by(ActivityLog.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify([log_dict(l) for l in rows])
