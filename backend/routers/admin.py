import time
from datetime import datetime, timedelta
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from database import get_db
from models import User, UserSubscription, RentalLog, RentalStatus
from schemas import AdminUserResponse, AdminStatsResponse, AdminRentalLogResponse
from security import get_current_admin

router = APIRouter(prefix="/admin", tags=["admin"])

_stats_cache: dict = {}
_stats_cache_ts: float = 0.0
_STATS_TTL = 60.0


@router.get("/stats", response_model=AdminStatsResponse)
def stats(db: Session = Depends(get_db), _=Depends(get_current_admin)):
    global _stats_cache, _stats_cache_ts
    if _stats_cache and time.monotonic() - _stats_cache_ts < _STATS_TTL:
        return _stats_cache

    total_users = db.query(User).filter(User.is_admin == False).count()
    active_subs = db.query(UserSubscription).filter(UserSubscription.status == RentalStatus.active).count()
    total_logs = db.query(RentalLog).count()

    bucket_count = 0
    try:
        from ministack_client import get_s3
        buckets = get_s3().list_buckets().get("Buckets", [])
        bucket_count = len(buckets)
    except Exception:
        pass

    _stats_cache = {
        "total_users": total_users,
        "active_subscriptions": active_subs,
        "total_logs": total_logs,
        "total_buckets": bucket_count,
    }
    _stats_cache_ts = time.monotonic()
    return _stats_cache


@router.get("/users", response_model=List[AdminUserResponse])
def all_users(db: Session = Depends(get_db), _=Depends(get_current_admin)):
    users = db.query(User).order_by(User.created_at.desc()).all()

    # Single aggregation query instead of one COUNT per user (N+1 → 2 queries total).
    counts = dict(
        db.query(UserSubscription.user_id, func.count(UserSubscription.id))
        .filter(UserSubscription.status == RentalStatus.active)
        .group_by(UserSubscription.user_id)
        .all()
    )

    return [
        AdminUserResponse(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            is_admin=u.is_admin,
            created_at=u.created_at,
            active_subscriptions=counts.get(u.id, 0),
        )
        for u in users
    ]


@router.get("/logs", response_model=List[AdminRentalLogResponse])
def all_logs(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
    limit: int = Query(50, ge=1, le=200),
    before_id: int | None = Query(None, description="Return logs with id < before_id (keyset pagination)"),
):
    q = (
        db.query(RentalLog)
        .options(joinedload(RentalLog.package), joinedload(RentalLog.user))
    )
    if before_id is not None:
        q = q.filter(RentalLog.id < before_id)
    return q.order_by(RentalLog.id.desc()).limit(limit).all()


_LOG_RETENTION_DAYS = 90


@router.delete("/logs/purge", status_code=200)
def purge_old_logs(
    db: Session = Depends(get_db),
    _=Depends(get_current_admin),
    days: int = Query(_LOG_RETENTION_DAYS, ge=30, description="Delete logs older than this many days"),
):
    """Delete rental_logs older than `days` days. Keeps the table from growing unbounded."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    deleted = db.query(RentalLog).filter(RentalLog.timestamp < cutoff).delete(synchronize_session=False)
    db.commit()
    # bust the stats cache so the log count reflects the purge immediately
    global _stats_cache_ts
    _stats_cache_ts = 0.0
    return {"deleted_rows": deleted, "cutoff": cutoff.isoformat()}
