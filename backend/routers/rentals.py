import traceback
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError
from typing import List, Optional

from database import get_db
from models import User, SubscriptionPackage, UserSubscription, RentalLog, RentalStatus, RentalAction, PackageType
from schemas import SubscriptionResponse, RentalLogResponse
from security import get_current_user
from repository import subscription_with_package

router = APIRouter(prefix="/rentals", tags=["rentals"])


@router.post("/{package_id}", response_model=SubscriptionResponse, status_code=201)
def rent_package(
    package_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    package = db.query(SubscriptionPackage).filter(SubscriptionPackage.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")

    existing = db.query(UserSubscription).filter(
        UserSubscription.user_id == current_user.id,
        UserSubscription.package_id == package_id,
        UserSubscription.status == RentalStatus.active,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have an active subscription for this package")

    subscription = UserSubscription(
        user_id=current_user.id,
        package_id=package_id,
        status=RentalStatus.active,
    )
    db.add(subscription)
    try:
        # Commit here so the DB transaction (and its pooled connection) is released
        # before we make slow external network calls to MiniStack.
        # The partial unique index uq_active_sub_per_package enforces one active
        # sub per package atomically, handling concurrent requests safely.
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="You already have an active subscription for this package")
    db.refresh(subscription)

    resource_ref = None
    if package.type == PackageType.storage:
        from ministack_client import ensure_bucket
        bucket_name = f"user-{current_user.id}-storage-{subscription.id}"
        try:
            ensure_bucket(bucket_name)
            resource_ref = bucket_name
        except Exception as e:
            print(f"WARNING: Could not create bucket: {e}")
            traceback.print_exc()
    elif package.type == PackageType.compute:
        from ministack_client import provision_compute
        try:
            instance_id = provision_compute(current_user.id, subscription.id, package.quota_value)
            resource_ref = instance_id
        except Exception as e:
            print(f"WARNING: Could not provision compute: {e}")
            traceback.print_exc()

    # Second short transaction: persist resource_ref and write the audit log.
    subscription.resource_ref = resource_ref
    db.add(RentalLog(
        user_id=current_user.id,
        package_id=package_id,
        subscription_id=subscription.id,
        action=RentalAction.rent,
        resource_ref=resource_ref,
    ))
    db.commit()

    return subscription_with_package(db, subscription.id)


@router.delete("/{subscription_id}", response_model=SubscriptionResponse)
def release_package(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subscription = (
        db.query(UserSubscription)
        .filter(
            UserSubscription.id == subscription_id,
            UserSubscription.user_id == current_user.id,
            UserSubscription.status == RentalStatus.active,
        )
        .first()
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Active subscription not found")

    subscription.status = RentalStatus.cancelled
    db.add(RentalLog(
        user_id=current_user.id,
        package_id=subscription.package_id,
        subscription_id=subscription.id,
        action=RentalAction.release,
    ))
    db.commit()

    return subscription_with_package(db, subscription_id)


@router.get("/logs", response_model=List[RentalLogResponse])
def rental_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    before_id: Optional[int] = Query(None, description="Return logs with id < before_id (keyset pagination)"),
):
    q = (
        db.query(RentalLog)
        .options(joinedload(RentalLog.package))
        .filter(RentalLog.user_id == current_user.id)
    )
    if before_id is not None:
        q = q.filter(RentalLog.id < before_id)
    return q.order_by(RentalLog.id.desc()).limit(limit).all()
