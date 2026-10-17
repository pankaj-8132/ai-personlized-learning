import hashlib, secrets
from fastapi import Header, HTTPException
from .db import get_db


def hash_pw(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def new_salt() -> str:
    return secrets.token_hex(16)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def current_user(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(401, "Missing token")
    with get_db() as db:
        row = db.execute("SELECT id, username FROM users WHERE token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "Invalid token")
    return dict(row)
