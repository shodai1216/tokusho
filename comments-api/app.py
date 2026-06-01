"""CEG 飲み部図鑑 — コメントAPI（FastAPI + SQLite）

各メンバーページ（slug 単位）にニックネーム＋メッセージを投稿する小さなAPI。
nginx で ceg.tokusho.org/api/ → 127.0.0.1:8100 にプロキシして使う（同一オリジン）。

セキュリティ方針:
- 保存は生テキスト。表示側（comments.js）は textContent で挿入するため格納型XSSは発生しない。
- 入力長を制限（nickname<=30 / message<=500）。
- ハニーポット（website）が埋まっていたら保存せず成功扱い（bot対策）。
- IP単位の簡易レート制限（60秒で5件まで）。
"""
import os
import re
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from threading import Lock

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

DB_PATH = os.environ.get(
    "COMMENTS_DB", os.path.join(os.path.dirname(__file__), "comments.db")
)
SLUG_RE = re.compile(r"^[a-z0-9_-]{1,40}$")

RL_WINDOW = 60.0  # 秒
RL_MAX = 5        # 同一IPの最大投稿数 / RL_WINDOW

app = FastAPI(title="CEG Comments API")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS comments (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                slug       TEXT NOT NULL,
                nickname   TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_comments_slug ON comments(slug, id)"
        )
        conn.commit()


init_db()


class CommentIn(BaseModel):
    slug: str
    nickname: str = Field(min_length=1, max_length=30)
    message: str = Field(min_length=1, max_length=500)
    website: str = ""  # ハニーポット（人間は空のまま）

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        v = v.strip()
        if not SLUG_RE.match(v):
            raise ValueError("invalid slug")
        return v

    @field_validator("nickname", "message")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty")
        return v


_rl_lock = Lock()
_rl: dict[str, list[float]] = {}


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def rate_ok(ip: str) -> bool:
    now = time.time()
    with _rl_lock:
        bucket = [t for t in _rl.get(ip, []) if now - t < RL_WINDOW]
        if len(bucket) >= RL_MAX:
            _rl[ip] = bucket
            return False
        bucket.append(now)
        _rl[ip] = bucket
        return True


@app.get("/comments")
def list_comments(slug: str = Query(..., max_length=40)):
    slug = slug.strip()
    if not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="invalid slug")
    with closing(get_db()) as conn:
        rows = conn.execute(
            "SELECT nickname, message, created_at FROM comments "
            "WHERE slug = ? ORDER BY id DESC LIMIT 200",
            (slug,),
        ).fetchall()
    return {"comments": [dict(r) for r in rows]}


@app.post("/comments")
def create_comment(payload: CommentIn, request: Request):
    # ハニーポットが埋まっていたら保存せず成功扱い
    if payload.website:
        return {"ok": True}
    if not rate_ok(client_ip(request)):
        raise HTTPException(status_code=429, detail="too many requests")
    created_at = datetime.now(timezone.utc).isoformat()
    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO comments (slug, nickname, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            (payload.slug, payload.nickname, payload.message, created_at),
        )
        conn.commit()
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}
