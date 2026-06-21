from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    is_admin: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CredentialResponse(BaseModel):
    access_key: str
    secret_key: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PackageResponse(BaseModel):
    id: int
    name: str
    type: str
    quota_value: int
    quota_unit: str
    price: float
    description: Optional[str] = None

    model_config = {"from_attributes": True}


class SubscriptionResponse(BaseModel):
    id: int
    status: str
    resource_ref: Optional[str] = None
    quota_used: int = 0
    quota_remaining: Optional[int] = None
    rented_at: datetime
    expires_at: Optional[datetime] = None
    package: PackageResponse

    model_config = {"from_attributes": True}


class RentRequest(BaseModel):
    package_id: int


class RentalLogResponse(BaseModel):
    id: int
    action: str
    resource_ref: Optional[str] = None
    subscription_id: Optional[int] = None
    timestamp: datetime
    package: PackageResponse

    model_config = {"from_attributes": True}


class DashboardResponse(BaseModel):
    user: UserResponse
    subscriptions: List[SubscriptionResponse]


# Admin schemas — defined after PackageResponse and UserResponse
class AdminUserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    is_admin: bool
    created_at: datetime
    active_subscriptions: int = 0

    model_config = {"from_attributes": True}


class AdminStatsResponse(BaseModel):
    total_users: int
    active_subscriptions: int
    total_logs: int
    total_buckets: int


class AdminRentalLogResponse(BaseModel):
    id: int
    action: str
    resource_ref: Optional[str] = None
    subscription_id: Optional[int] = None
    timestamp: datetime
    package: PackageResponse
    user: UserResponse

    model_config = {"from_attributes": True}
