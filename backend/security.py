"""Auth + crypto helpers for the Flask app.

- Passwords: bcrypt hashes.
- Sessions: short JWTs (PyJWT) carrying the user id; sent as `Authorization: Bearer`.
- Stored secret keys: Fernet-encrypted at rest, decrypted only for the owner.
"""
import os
import base64
import hashlib
from datetime import datetime, timedelta
from functools import wraps

import bcrypt
import jwt
from cryptography.fernet import Fernet
from flask import request, jsonify, g
from dotenv import load_dotenv

from database import db_session
from models import User, UserStatus

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-to-a-long-random-string")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))


# --- Fernet key -------------------------------------------------------------
def _load_fernet() -> Fernet:
    key = os.getenv("FERNET_KEY")
    if not key:
        # No key configured (dev/test): derive a stable one from JWT_SECRET so the
        # app still runs. NEVER rely on this in production — set FERNET_KEY.
        digest = hashlib.sha256(JWT_SECRET.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


_fernet = _load_fernet()


def encrypt_secret(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


# --- Passwords --------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# --- JWT --------------------------------------------------------------------
def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _user_from_request():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None
    return db_session.query(User).filter(User.id == user_id).first()


def login_required(fn):
    """Decorator: rejects with 401 unless a valid token maps to an active user.

    The resolved user is stashed on flask.g.current_user for the view.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = _user_from_request()
        if not user:
            return jsonify({"detail": "Invalid or expired token"}), 401
        if user.status == UserStatus.suspended:
            return jsonify({"detail": "Account suspended"}), 403
        g.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not g.current_user.is_admin:
            return jsonify({"detail": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper
