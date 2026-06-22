"""Storage platform schema — mirrors the DBML in SKILL.md §4.

A self-service "rent-a-bucket" model: users subscribe to a package (which sets a
byte quota), the system provisions one isolated S3 bucket + a credential pair per
user in MiniStack, and objects are stored against the subscription's used_bytes.
"""
import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime,
    ForeignKey, Numeric, Text, Enum, Index, UniqueConstraint, text,
)
from sqlalchemy.orm import relationship
from database import Base


class UserStatus(str, enum.Enum):
    active = "active"
    suspended = "suspended"


class SubStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


class CredStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"


class LogAction(str, enum.Enum):
    register = "register"
    subscribe = "subscribe"
    bucket_created = "bucket_created"
    key_generated = "key_generated"
    upload = "upload"
    download = "download"
    delete = "delete"
    quota_exceeded = "quota_exceeded"
    credit_added = "credit_added"     # admin topped up a user's balance
    payment = "payment"               # user spent credits on a package


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    status = Column(Enum(UserStatus), default=UserStatus.active, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    # Prepaid balance (credits = money). Spent when subscribing to / upgrading a
    # package; only an admin can top it up.
    credits = Column(Numeric(10, 2), default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("Subscription", back_populates="user")
    buckets = relationship("Bucket", back_populates="user")
    credentials = relationship("Credential", back_populates="user")
    logs = relationship("ActivityLog", back_populates="user")


class Package(Base):
    """Seeded with at least 3 rows (Free / Basic / Pro); the quota lives here."""
    __tablename__ = "packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    quota_bytes = Column(BigInteger, nullable=False)
    max_buckets = Column(Integer, default=1, nullable=False)
    price = Column(Numeric(10, 2), default=0, nullable=False)
    description = Column(Text, nullable=True)

    subscriptions = relationship("Subscription", back_populates="package")


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subs_user_status", "user_id", "status"),
        # At most one active subscription per user (skill §4 "strict" note).
        Index(
            "uq_active_sub_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    package_id = Column(Integer, ForeignKey("packages.id"), nullable=False)
    # Fast usage counter, bumped on every upload/delete and reconciled by the worker.
    used_bytes = Column(BigInteger, default=0, nullable=False)
    status = Column(Enum(SubStatus), default=SubStatus.active, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="subscriptions")
    package = relationship("Package", back_populates="subscriptions")
    buckets = relationship("Bucket", back_populates="subscription")

    @property
    def quota_bytes(self):
        return self.package.quota_bytes if self.package else None

    @property
    def quota_remaining(self):
        if self.package:
            return self.package.quota_bytes - self.used_bytes
        return None


class Bucket(Base):
    """One isolated bucket per user, created in MiniStack on subscribe."""
    __tablename__ = "buckets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    name = Column(String(255), unique=True, nullable=False)
    region = Column(String(64), default="us-east-1", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="buckets")
    subscription = relationship("Subscription", back_populates="buckets")
    objects = relationship("StoredObject", back_populates="bucket")


class Credential(Base):
    """Access Key + Secret Key pair. The secret is stored Fernet-encrypted, never plaintext."""
    __tablename__ = "credentials"
    __table_args__ = (
        Index("ix_cred_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    access_key_id = Column(String(128), unique=True, nullable=False)
    secret_key_encrypted = Column(String(512), nullable=False)
    status = Column(Enum(CredStatus), default=CredStatus.active, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="credentials")


class StoredObject(Base):
    """Object metadata mirror — powers fast listing and worker reconciliation."""
    __tablename__ = "objects"
    __table_args__ = (
        UniqueConstraint("bucket_id", "object_key", name="uq_bucket_object"),
    )

    id = Column(Integer, primary_key=True, index=True)
    bucket_id = Column(Integer, ForeignKey("buckets.id"), nullable=False)
    object_key = Column(String(1024), nullable=False)
    size_bytes = Column(BigInteger, default=0, nullable=False)
    content_type = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    bucket = relationship("Bucket", back_populates="objects")


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("ix_log_user_ts", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(Enum(LogAction), nullable=False)
    detail = Column(String(512), nullable=True)
    bytes = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="logs")
