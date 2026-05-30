import uuid, hashlib
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.database import get_db
from app.auth import sha256, is_expired

router = APIRouter()

class OtpRequest(BaseModel):
    displayName: str
    expiresInHours: Optional[int] = None
    maxUses: Optional[int] = None
    sessionToken: str

@router.post("/otp")
def create_otp(body: OtpRequest):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE token=%s", (body.sessionToken,))
            s = cur.fetchone()
    if not s or is_expired(s["expires_at"]):
        return {"success":False,"message":"ログインが必要です"}

    user_id  = "guest_" + str(uuid.uuid4())[:8]
    password = str(uuid.uuid4()).replace("-","")[:12]
    pw_hash  = sha256(password)
    expires  = None
    if body.expiresInHours:
        expires = (datetime.now(timezone.utc) + timedelta(hours=body.expiresInHours)).isoformat()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (id, password_hash, display_name, expires_at, max_uses, use_count)
                VALUES (%s,%s,%s,%s,%s,0)
            """, (user_id, pw_hash, body.displayName, expires, body.maxUses))

    return {"success":True,"userId":user_id,"password":password,
            "expiresAt":expires,"maxUses":body.maxUses}
