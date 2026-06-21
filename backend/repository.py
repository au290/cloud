"""Shared data-access helpers to avoid duplicated query/credential logic across routers."""
from sqlalchemy.orm import Session, joinedload

from models import UserSubscription, AccessCredential, RentalStatus


def active_subscriptions(db: Session, user_id: int):
    """All active subscriptions for a user, with their package eager-loaded."""
    return (
        db.query(UserSubscription)
        .options(joinedload(UserSubscription.package))
        .filter(
            UserSubscription.user_id == user_id,
            UserSubscription.status == RentalStatus.active,
        )
        .all()
    )


def subscription_with_package(db: Session, subscription_id: int):
    """A single subscription by id with its package eager-loaded (for serialization)."""
    return (
        db.query(UserSubscription)
        .options(joinedload(UserSubscription.package))
        .filter(UserSubscription.id == subscription_id)
        .first()
    )


def active_credentials(db: Session, user_id: int):
    """All active access credentials for a user."""
    return (
        db.query(AccessCredential)
        .filter(
            AccessCredential.user_id == user_id,
            AccessCredential.is_active.is_(True),
        )
        .all()
    )


def issue_credentials(db: Session, user_id: int) -> AccessCredential:
    """Create IAM credentials in MiniStack and persist them for the user.

    Raises on failure; callers decide whether to tolerate or surface the error.
    """
    from ministack_client import create_iam_user_credentials

    creds = create_iam_user_credentials(f"user-{user_id}")
    credential = AccessCredential(
        user_id=user_id,
        access_key=creds["access_key"],
        secret_key=creds["secret_key"],
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential
