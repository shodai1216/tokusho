from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timezone
import os
from app.database import get_db
from app.auth import sha256, new_session_token, session_expires, is_expired

router  = APIRouter()
ADMIN_PW = os.getenv("ADMIN_PASSWORD")

@router.get("/status")
def get_status():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM device_status WHERE id=1")
            row = cur.fetchone()
    if not row:
        return {"state":"unknown","door":"unknown","thumb":"unknown","error":"","lastUpdated":"-"}
    ts = row["last_updated"]
    if ts and ts.tzinfo:
        import datetime as dt_mod
        JST = dt_mod.timezone(dt_mod.timedelta(hours=9))
        ts_str = ts.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S")
    else:
        ts_str = "-"
    return {"state":row["state"],"door":row["door"],"thumb":row["thumb"],
            "error":row["error"],"lastUpdated":ts_str}

@router.get("/logs")
def get_logs(limit: int = 20):
    import datetime as dt_mod
    JST = dt_mod.timezone(dt_mod.timedelta(hours=9))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    result = []
    for r in rows:
        ts = r["timestamp"]
        t_str = ts.astimezone(JST).strftime("%m/%d %H:%M:%S") if ts else "-"
        result.append({"time":t_str,"state":r["state"] or "",
                        "door":r["door"] or "","thumb":r["thumb"] or "",
                        "userId":r["user_id"] or "","error":r["error"] or ""})
    return result

class LoginRequest(BaseModel):
    userId: str
    password: str

@router.post("/login")
def login(body: LoginRequest):
    uid  = body.userId.strip()
    pw   = body.password

    if uid == "admin" and ADMIN_PW and pw == ADMIN_PW:
        token = new_session_token()
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sessions (token,user_id,display_name,expires_at) VALUES(%s,%s,%s,%s)",
                    (token, "admin", "管理者", session_expires())
                )
        return {"success":True,"token":token,"displayName":"管理者","isAdmin":True}

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
            user = cur.fetchone()

    if not user or user["password_hash"] != sha256(pw):
        return {"success":False,"message":"IDまたはパスワードが正しくありません"}
    if is_expired(user["expires_at"]):
        return {"success":False,"message":"有効期限が切れています"}
    if user["max_uses"] is not None and user["use_count"] >= user["max_uses"]:
        return {"success":False,"message":"使用回数の上限に達しています"}

    if user["max_uses"] is not None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET use_count=use_count+1 WHERE id=%s", (uid,))

    token = new_session_token()
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sessions (token,user_id,display_name,expires_at) VALUES(%s,%s,%s,%s)",
                (token, user["id"], user["display_name"] or user["id"], session_expires())
            )
    return {"success":True,"token":token,"displayName":user["display_name"] or user["id"],"isAdmin":False}

@router.get("/session/{token}")
def validate_session(token: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE token=%s", (token,))
            s = cur.fetchone()
    if not s or is_expired(s["expires_at"]):
        return None
    return {"userId":s["user_id"],"displayName":s["display_name"] or s["user_id"]}

class SessionRequest(BaseModel):
    token: str

@router.post("/unlock")
def unlock(body: SessionRequest):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE token=%s", (body.token,))
            s = cur.fetchone()
    if not s or is_expired(s["expires_at"]):
        return {"success":False,"message":"セッションが無効です","needLogin":True}

    name = s["display_name"] or s["user_id"]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO commands (command,operator) VALUES('unlock',%s)", (name,))
            cur.execute("INSERT INTO logs (state,user_id) VALUES('unlock_requested',%s)", (name,))
    return {"success":True,"displayName":name}

@router.post("/lock")
def lock():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO commands (command,operator) VALUES('lock','web')")
            cur.execute("INSERT INTO logs (state) VALUES('lock_requested')")
    return {"success":True}
