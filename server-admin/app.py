"""Tokusho サーバー管理API（FastAPI）

apex（tokusho.org）の管理ポータル用バックエンド。稼働確認・サービス操作・
デプロイ（git pull）・nginx リロード・再起動・CEGコメント管理を行う。

セキュリティ方針:
- 127.0.0.1:8200 のみで待受。外部からは nginx の Basic認証の内側でしか到達できない。
- /webhook のみ Basic認証なし（GitHub から到達できるよう nginx で例外）。HMAC-SHA256 で検証。
- サービス名は ALLOWED、操作は ACTIONS の許可リストで検証。
- subprocess は配列実行（シェル無し）→ コマンドインジェクション不可。
- 特権操作は sudoers で当該コマンドのみ NOPASSWD 許可（server-admin/sudoers.tokusho-admin）。
- 自分自身（tokusho-admin）の stop / disable はロックアウト防止のためブロック。
"""
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import threading
import time
import urllib.request
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

# 操作を許可するサービス（systemd ユニット名 → 表示名）
ALLOWED = {
    "nginx": "Nginx",
    "cloudflared": "Cloudflare Tunnel",
    "ceg-comments": "CEG コメントAPI",
    "tokusho-admin": "管理API（自身）",
    "smartlock": "SmartLock API",
}
ACTIONS = {"start", "stop", "restart", "enable", "disable"}
# サービスごとに禁止する操作（自分を止めると復帰不能になるため）
BLOCKED = {"tokusho-admin": {"stop", "disable"}}

REPO_DIR = os.environ.get("REPO_DIR", "/home/shodai/tokusho")
COMMENTS_DB = os.environ.get("COMMENTS_DB", "/home/shodai/data/ceg_comments.db")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
MAX_LOG_LINES = 300

_SEP = "-" * 24  # Discord メッセージの区切り線


# ── Discord 通知 ──────────────────────────────────────────────────────────────

def notify_discord(title: str, body: str = ""):
    """Discord Webhook に通知を送る。失敗してもAPIの動作は止めない。"""
    if not DISCORD_WEBHOOK:
        return
    lines = [_SEP, title]
    if body:
        lines.append(body)
    lines.append(time.strftime("%Y-%m-%d %H:%M:%S"))
    lines.append(_SEP)
    msg = "\n".join(lines)
    try:
        data = json.dumps({"content": f"```\n{msg}\n```"}).encode()
        req = urllib.request.Request(
            DISCORD_WEBHOOK, data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(
        target=notify_discord, args=("✅ tokusho-admin 起動",), daemon=True
    ).start()
    yield


app = FastAPI(title="Tokusho Server Admin", lifespan=lifespan)


# ── 内部ユーティリティ ────────────────────────────────────────────────────────

def run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def systemctl_query(verb: str, svc: str) -> str:
    try:
        r = run(["systemctl", verb, svc], timeout=5)
        return (r.stdout.strip() or r.stderr.strip() or "unknown")
    except Exception:
        return "unknown"


def _first_line(path: str) -> str:
    try:
        with open(path) as f:
            return f.readline().strip()
    except Exception:
        return ""


def system_info():
    uptime = ""
    try:
        secs = float(_first_line("/proc/uptime").split()[0])
        d, rem = divmod(int(secs), 86400)
        h, rem = divmod(rem, 3600)
        m, _ = divmod(rem, 60)
        uptime = (f"{d}d " if d else "") + f"{h}h {m}m"
    except Exception:
        pass

    load = _first_line("/proc/loadavg").split()[:3]
    load = " ".join(load) if load else "-"

    disk = None
    try:
        import shutil
        total, used, _free = shutil.disk_usage("/")
        disk = {"used": used, "total": total, "pct": round(used / total * 100)}
    except Exception:
        pass

    mem = None
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k] = int(v.strip().split()[0])  # kB
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", 0)
        used = total - avail
        mem = {
            "used": used * 1024,
            "total": total * 1024,
            "pct": round(used / total * 100) if total else 0,
        }
    except Exception:
        pass

    return {"uptime": uptime, "load": load, "disk": disk, "mem": mem}


# ── エンドポイント ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/status")
def status():
    services = []
    for k, v in ALLOWED.items():
        services.append({
            "id": k,
            "label": v,
            "active": systemctl_query("is-active", k),
            "enabled": systemctl_query("is-enabled", k),
            "blocked": sorted(BLOCKED.get(k, set())),
        })
    return {
        "services": services,
        "system": system_info(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


class ServiceAction(BaseModel):
    service: str
    action: str


@app.post("/service")
def service_action(p: ServiceAction):
    if p.service not in ALLOWED:
        raise HTTPException(status_code=400, detail="service not allowed")
    if p.action not in ACTIONS:
        raise HTTPException(status_code=400, detail="action not allowed")
    if p.action in BLOCKED.get(p.service, set()):
        raise HTTPException(status_code=403, detail=f"'{p.action}' is blocked for {p.service}")
    try:
        r = run(["sudo", "-n", "systemctl", p.action, p.service], timeout=30)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="systemctl timed out")
    ok = r.returncode == 0
    if ok and p.action in {"start", "stop", "restart"}:
        label = ALLOWED[p.service]
        icons = {"start": "▶️", "stop": "⏹️", "restart": "🔄"}
        threading.Thread(
            target=notify_discord,
            args=(f"{icons[p.action]} {label} {p.action}",),
            daemon=True,
        ).start()
    return {
        "ok": ok,
        "service": p.service,
        "action": p.action,
        "active": systemctl_query("is-active", p.service),
        "enabled": systemctl_query("is-enabled", p.service),
        "message": "done" if ok else (r.stderr.strip() or r.stdout.strip())[:500],
    }


@app.post("/deploy")
def deploy():
    def head():
        return run(["git", "-C", REPO_DIR, "rev-parse", "HEAD"]).stdout.strip()

    before = head()
    try:
        r = run(["git", "-C", REPO_DIR, "pull", "--ff-only"], timeout=120)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="git pull timed out")
    after = head()
    changed = []
    if before and after and before != after:
        d = run(["git", "-C", REPO_DIR, "diff", "--name-only", before, after])
        changed = d.stdout.splitlines()

    if r.returncode == 0:
        body_lines = [f"{before[:7]} → {after[:7]}"]
        if changed:
            preview = ", ".join(changed[:5]) + ("…" if len(changed) > 5 else "")
            body_lines.append(f"変更: {preview}")
        threading.Thread(
            target=notify_discord,
            args=("🚀 デプロイ完了", "\n".join(body_lines)),
            daemon=True,
        ).start()

    return {
        "ok": r.returncode == 0,
        "before": before[:8],
        "after": after[:8],
        "changed": changed,
        "output": (r.stdout + r.stderr).strip()[:4000],
    }


@app.post("/nginx/reload")
def nginx_reload():
    t = run(["sudo", "-n", "nginx", "-t"], timeout=15)
    if t.returncode != 0:
        return {"ok": False, "stage": "test", "output": (t.stdout + t.stderr).strip()[:3000]}
    r = run(["sudo", "-n", "systemctl", "reload", "nginx"], timeout=20)
    return {
        "ok": r.returncode == 0,
        "stage": "reload",
        "output": ((t.stdout + t.stderr) + "\n" + (r.stdout + r.stderr)).strip()[:3000],
    }


@app.post("/reboot")
def reboot():
    notify_discord("🔄 サーバー再起動")
    try:
        subprocess.Popen(["sudo", "-n", "systemctl", "reboot"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "message": "reboot signal sent"}


@app.get("/logs")
def logs(
    service: str = Query(...),
    lines: int = Query(100, ge=1, le=MAX_LOG_LINES),
):
    if service not in ALLOWED:
        raise HTTPException(status_code=400, detail="service not allowed")
    try:
        r = run(
            ["sudo", "-n", "journalctl", "-u", service, "-n", str(lines),
             "--no-pager", "--output=short-iso"],
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="log read timed out")
    if r.returncode != 0:
        raise HTTPException(status_code=500, detail=(r.stderr.strip() or "journalctl failed")[:500])
    return {"service": service, "lines": r.stdout.splitlines()[-lines:]}


# ── CEGコメント管理（comments-api と同じSQLiteを直接参照） ──────────────────

def _comments_conn():
    if not os.path.exists(COMMENTS_DB):
        raise HTTPException(status_code=404, detail="comments db not found")
    conn = sqlite3.connect(COMMENTS_DB)
    conn.row_factory = sqlite3.Row
    return conn


@app.get("/comments")
def list_comments(
    slug: str = Query(None),
    limit: int = Query(200, ge=1, le=500),
):
    conn = _comments_conn()
    try:
        if slug:
            rows = conn.execute(
                "SELECT id, slug, nickname, message, created_at FROM comments "
                "WHERE slug = ? ORDER BY id DESC LIMIT ?",
                (slug, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, slug, nickname, message, created_at FROM comments "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return {"comments": [dict(r) for r in rows]}
    finally:
        conn.close()


class DeleteComment(BaseModel):
    id: int


@app.post("/comments/delete")
def delete_comment(p: DeleteComment):
    conn = _comments_conn()
    try:
        cur = conn.execute("DELETE FROM comments WHERE id = ?", (p.id,))
        conn.commit()
        return {"ok": True, "deleted": cur.rowcount}
    finally:
        conn.close()


# ── GitHub Webhook 自動デプロイ ───────────────────────────────────────────────

def _webhook_deploy():
    """Webhook からのデプロイを非同期で実行する（BackgroundTasks から呼ばれる）。"""
    def head():
        return run(["git", "-C", REPO_DIR, "rev-parse", "HEAD"]).stdout.strip()

    before = head()
    try:
        r = run(["git", "-C", REPO_DIR, "pull", "--ff-only"], timeout=120)
    except subprocess.TimeoutExpired:
        notify_discord("❌ Webhook デプロイ失敗", "git pull timed out")
        return

    if r.returncode != 0:
        notify_discord("❌ Webhook デプロイ失敗", r.stderr.strip()[:300])
        return

    after = head()
    changed = []
    if before and after and before != after:
        d = run(["git", "-C", REPO_DIR, "diff", "--name-only", before, after])
        changed = d.stdout.splitlines()

    body_lines = [f"{before[:7]} → {after[:7]}"]
    if changed:
        preview = ", ".join(changed[:5]) + ("…" if len(changed) > 5 else "")
        body_lines.append(f"変更: {preview}")
    notify_discord("🚀 Webhook デプロイ完了", "\n".join(body_lines))

    # 変更内容に応じてサービスを再起動
    if any(f.startswith("server-admin/") for f in changed):
        time.sleep(2)  # 通知送信を待ってから自己再起動
        subprocess.Popen(["sudo", "-n", "systemctl", "restart", "tokusho-admin"])
    if any(f.startswith("comments-api/") for f in changed):
        run(["sudo", "-n", "systemctl", "restart", "ceg-comments"], timeout=30)


@app.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """GitHub Webhook エンドポイント（nginx で auth_basic off）。

    GITHUB_WEBHOOK_SECRET が設定されている場合は X-Hub-Signature-256 で検証する。
    main ブランチへの push のみデプロイを実行する。
    """
    body = await request.body()

    secret = GITHUB_WEBHOOK_SECRET
    if secret:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(status_code=403, detail="signature mismatch")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")

    ref = payload.get("ref", "")
    if ref != "refs/heads/main":
        return {"ok": True, "message": f"ignored ref: {ref}"}

    background_tasks.add_task(_webhook_deploy)
    return {"ok": True, "message": "deploy triggered"}
