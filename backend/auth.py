"""
Auth -- JWT-based, same pattern as the OAuth2/JWT step from the original
plan. SECRET_KEY must be overridden via an env var in anything beyond
local dev; the fallback here exists purely so the app runs out of the box.

The permission model this enforces:
    Alice owns Device A
    Alice shares Device A with Bob  -> Bob can view it
    Charlie has no grant            -> Charlie cannot view it (403, not just hidden UI)
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

import models
from database import get_db

SECRET_KEY = os.getenv("JWT_SECRET", "dev-secret-change-before-deploying")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 day

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


def can_view_device(db: Session, user: models.User, device_id: int) -> bool:
    """True if user owns the device OR has an active share grant on it."""
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        return False
    if device.owner_user_id == user.id:
        return True

    grant = (
        db.query(models.SharePermission)
        .filter(
            models.SharePermission.device_id == device_id,
            models.SharePermission.viewer_user_id == user.id,
            models.SharePermission.active == True,  # noqa: E712 -- SQLAlchemy needs `== True`, not `is True`
        )
        .first()
    )
    return grant is not None


def require_view_access(db: Session, user: models.User, device_id: int):
    if not can_view_device(db, user, device_id):
        raise HTTPException(status_code=403, detail="You don't have access to this device's data")


def require_owner(db: Session, user: models.User, device_id: int) -> models.Device:
    device = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if device.owner_user_id != user.id:
        raise HTTPException(status_code=403, detail="Only the device owner can do this")
    return device
