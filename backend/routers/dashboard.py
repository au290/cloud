from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import User
from schemas import DashboardResponse, SubscriptionResponse, CredentialResponse
from security import get_current_user
from repository import active_subscriptions, active_credentials, issue_credentials

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
@router.get("/", response_model=DashboardResponse)
def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    subscriptions = active_subscriptions(db, current_user.id)
    return {"user": current_user, "subscriptions": subscriptions}


@router.get("/quota", response_model=List[SubscriptionResponse])
def quota(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return active_subscriptions(db, current_user.id)


@router.get("/credentials", response_model=List[CredentialResponse])
def list_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return active_credentials(db, current_user.id)


@router.post("/credentials", response_model=CredentialResponse, status_code=201)
def request_credentials(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return issue_credentials(db, current_user.id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate credentials: {e}")
