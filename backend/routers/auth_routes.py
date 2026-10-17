from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..db import get_db
from ..auth import hash_pw, new_salt, new_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Creds(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=6, max_length=100)


@router.post("/register")
def register(c: Creds):
    salt, token = new_salt(), new_token()
    with get_db() as db:
        if db.execute("SELECT 1 FROM users WHERE username=?", (c.username,)).fetchone():
            raise HTTPException(409, "Username taken")
        db.execute("INSERT INTO users(username,salt,pw_hash,token) VALUES(?,?,?,?)",
                   (c.username, salt, hash_pw(c.password, salt), token))
    return {"token": token, "username": c.username}


@router.post("/login")
def login(c: Creds):
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE username=?", (c.username,)).fetchone()
        if not u or hash_pw(c.password, u["salt"]) != u["pw_hash"]:
            raise HTTPException(401, "Wrong username or password")
        token = new_token()
        db.execute("UPDATE users SET token=? WHERE id=?", (token, u["id"]))
    return {"token": token, "username": c.username}
