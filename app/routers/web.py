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

def _require_admin(token: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions WHERE token=%s", (token,))
            s = cur.fetchone()
    if not s or is_expired(s["expires_at"]) or s["user_id"] != "admin":
        return None
    return s

# ── ユーザー一覧 ──────────────────────────────────
@router.get("/admin/users")
def list_users(token: str):
    if not _require_admin(token):
        return {"success": False, "message": "管理者権限が必要です"}
    import datetime as dt_mod
    JST = dt_mod.timezone(dt_mod.timedelta(hours=9))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users ORDER BY created_at DESC")
            rows = cur.fetchall()
    result = []
    for r in rows:
        exp = r["expires_at"]
        exp_str = exp.astimezone(JST).strftime("%Y/%m/%d %H:%M") if exp else "無制限"
        result.append({
            "id":          r["id"],
            "displayName": r["display_name"] or r["id"],
            "expiresAt":   exp_str,
            "maxUses":     r["max_uses"],
            "useCount":    r["use_count"],
            "expired":     is_expired(exp) if exp else False,
        })
    return {"success": True, "users": result}

# ── ユーザー削除 ──────────────────────────────────
class AdminUserRequest(BaseModel):
    token: str
    userId: str

@router.post("/admin/users/delete")
def delete_user(body: AdminUserRequest):
    if not _require_admin(body.token):
        return {"success": False, "message": "管理者権限が必要です"}
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE user_id=%s", (body.userId,))
            cur.execute("DELETE FROM users WHERE id=%s", (body.userId,))
    return {"success": True}

# ── セッション一覧 ────────────────────────────────
@router.get("/admin/sessions")
def list_sessions(token: str):
    if not _require_admin(token):
        return {"success": False, "message": "管理者権限が必要です"}
    import datetime as dt_mod
    JST = dt_mod.timezone(dt_mod.timedelta(hours=9))
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sessions ORDER BY expires_at DESC")
            rows = cur.fetchall()
    result = []
    for r in rows:
        exp = r["expires_at"]
        exp_str = exp.astimezone(JST).strftime("%Y/%m/%d %H:%M") if exp else "-"
        result.append({
            "token":       r["token"][:8] + "...",
            "fullToken":   r["token"],
            "userId":      r["user_id"],
            "displayName": r["display_name"] or r["user_id"],
            "expiresAt":   exp_str,
            "expired":     is_expired(exp),
        })
    return {"success": True, "sessions": result}

# ── セッション削除 ────────────────────────────────
class AdminSessionRequest(BaseModel):
    token: str
    targetToken: str

@router.post("/admin/sessions/delete")
def delete_session(body: AdminSessionRequest):
    if not _require_admin(body.token):
        return {"success": False, "message": "管理者権限が必要です"}
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token=%s", (body.targetToken,))
    return {"success": True}
