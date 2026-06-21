from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    ForeignKey, Numeric, Text, Enum, Index, text
)
from sqlalchemy.orm import relationship
from database import Base
import enum


class PackageType(str, enum.Enum):
    compute = "compute"
    storage = "storage"
    network = "network"


class RentalStatus(str, enum.Enum):
    active = "active"
    expired = "expired"
    cancelled = "cancelled"


class RentalAction(str, enum.Enum):
    rent = "rent"
    release = "release"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    subscriptions = relationship("UserSubscription", back_populates="user")
    rental_logs = relationship("RentalLog", back_populates="user")
    credentials = relationship("AccessCredential", back_populates="user")


class SubscriptionPackage(Base):
    __tablename__ = "subscription_packages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    type = Column(Enum(PackageType), nullable=False)
    quota_value = Column(Integer, nullable=False)
    quota_unit = Column(String(20), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    description = Column(Text, nullable=True)

    subscriptions = relationship("UserSubscription", back_populates="package")
    rental_logs = relationship("RentalLog", back_populates="package")


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        Index("ix_subs_user_status", "user_id", "status"),
        # prevents duplicate active subs at the DB level (TOCTOU-safe)
        Index(
            "uq_active_sub_per_package",
            "user_id", "package_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    package_id = Column(Integer, ForeignKey("subscription_packages.id"), nullable=False)
    status = Column(Enum(RentalStatus), default=RentalStatus.active, nullable=False)
    resource_ref = Column(String(255), nullable=True)
    quota_used = Column(Integer, default=0, nullable=False)
    rented_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="subscriptions")
    package = relationship("SubscriptionPackage", back_populates="subscriptions")

    @property
    def quota_remaining(self):
        if self.package:
            return self.package.quota_value - self.quota_used
        return None


class RentalLog(Base):
    __tablename__ = "rental_logs"
    __table_args__ = (
        # covers per-user log queries ordered by time
        Index("ix_log_user_ts", "user_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    package_id = Column(Integer, ForeignKey("subscription_packages.id"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("user_subscriptions.id"), nullable=True)
    action = Column(Enum(RentalAction), nullable=False)
    resource_ref = Column(String(255), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="rental_logs")
    package = relationship("SubscriptionPackage", back_populates="rental_logs")
    subscription = relationship("UserSubscription")


class AccessCredential(Base):
    __tablename__ = "access_credentials"
    __table_args__ = (
        Index("ix_cred_user_active", "user_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    access_key = Column(String(100), unique=True, nullable=False)
    secret_key = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    user = relationship("User", back_populates="credentials")
