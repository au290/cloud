import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import SubscriptionPackage
from schemas import PackageResponse

router = APIRouter(prefix="/packages", tags=["packages"])

_packages_cache: list = []
_packages_cache_ts: float = 0.0
_PACKAGES_TTL = 300.0  # packages rarely change; refresh every 5 minutes


@router.get("", response_model=List[PackageResponse])
@router.get("/", response_model=List[PackageResponse])
def list_packages(db: Session = Depends(get_db)):
    global _packages_cache, _packages_cache_ts
    if _packages_cache and time.monotonic() - _packages_cache_ts < _PACKAGES_TTL:
        return _packages_cache
    packages = db.query(SubscriptionPackage).all()
    db.expunge_all()  # detach objects so they outlive this session safely
    _packages_cache = packages
    _packages_cache_ts = time.monotonic()
    return packages


@router.get("/{package_id}", response_model=PackageResponse)
def get_package(package_id: int, db: Session = Depends(get_db)):
    package = db.query(SubscriptionPackage).filter(SubscriptionPackage.id == package_id).first()
    if not package:
        raise HTTPException(status_code=404, detail="Package not found")
    return package
