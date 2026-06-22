"""Provisioning flow (skill §5): on sign-up create the subscription, the isolated
bucket, and the credential pair, logging each step.

Kept separate from the HTTP blueprints so both /api/register and /api/subscriptions
can reuse it, and so the worker / tests can call it directly.
"""
import logging

from database import db_session
from models import (
    User, Package, Subscription, Bucket, Credential, ActivityLog,
    SubStatus, CredStatus, LogAction,
)
import ministack_client as ms
from security import encrypt_secret

log = logging.getLogger("iaas.provisioning")


def log_action(user_id: int, action: LogAction, detail: str = None, num_bytes: int = None):
    db_session.add(ActivityLog(user_id=user_id, action=action, detail=detail, bytes=num_bytes))


def bucket_name_for(user: User) -> str:
    return f"bucket-user-{user.id}"


def issue_credentials(user: User) -> tuple[Credential, str]:
    """Mint a key pair, store the secret encrypted, and return (credential, plaintext_secret).

    The plaintext secret is returned ONLY here so the caller can show it once (AWS-style).
    """
    keys = ms.create_user_credentials(f"user-{user.id}")
    cred = Credential(
        user_id=user.id,
        access_key_id=keys["access_key"],
        secret_key_encrypted=encrypt_secret(keys["secret_key"]),
        status=CredStatus.active,
    )
    db_session.add(cred)
    log_action(user.id, LogAction.key_generated, detail=keys["access_key"])
    return cred, keys["secret_key"]


def ensure_bucket(user: User, subscription: Subscription) -> Bucket:
    """Create (or reuse) the user's isolated bucket and persist its metadata row."""
    existing = db_session.query(Bucket).filter(Bucket.user_id == user.id).first()
    name = existing.name if existing else bucket_name_for(user)
    region = existing.region if existing else "us-east-1"
    try:
        ms.create_bucket(name, region)
    except Exception as e:
        log.error("Bucket provisioning failed for user=%s: %s", user.id, e)
        raise
    if existing:
        existing.subscription_id = subscription.id
        return existing
    bucket = Bucket(user_id=user.id, subscription_id=subscription.id, name=name, region=region)
    db_session.add(bucket)
    log_action(user.id, LogAction.bucket_created, detail=name)
    return bucket


def subscribe(user: User, package: Package) -> Subscription:
    """Create an active subscription for `package`, cancelling any existing active one.

    Carries used_bytes across a package switch (the stored data is unchanged).
    Provisions the bucket and ensures the user has at least one credential pair.
    """
    current = (
        db_session.query(Subscription)
        .filter(Subscription.user_id == user.id, Subscription.status == SubStatus.active)
        .first()
    )
    carried = current.used_bytes if current else 0
    if current:
        current.status = SubStatus.cancelled

    sub = Subscription(
        user_id=user.id,
        package_id=package.id,
        used_bytes=carried,
        status=SubStatus.active,
    )
    db_session.add(sub)
    db_session.flush()  # need sub.id for the bucket FK

    ensure_bucket(user, sub)
    log_action(user.id, LogAction.subscribe, detail=package.name)
    return sub


def provision_new_user(user: User, package: Package) -> str:
    """Full sign-up provisioning. Returns the one-time plaintext secret key."""
    subscribe(user, package)
    _, secret = issue_credentials(user)
    return secret


def reconcile_buckets() -> int:
    """Recreate any DB-known buckets that are missing in MiniStack.

    MiniStack loses in-memory state on restart (unless PERSIST_STATE is set), but the
    `buckets` table still remembers them. This idempotently re-creates each one so
    uploads keep working after a wipe. Returns the number of buckets ensured.
    Best-effort: failures are logged, not raised.
    """
    ensured = 0
    for b in db_session.query(Bucket).all():
        try:
            ms.create_bucket(b.name, b.region)  # idempotent (head_bucket first)
            ensured += 1
        except Exception as e:
            log.warning("Could not ensure bucket %s: %s", b.name, e)
    return ensured
