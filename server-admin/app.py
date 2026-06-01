"""Tokusho サーバー管理API（FastAPI）

apex（tokusho.org）の管理ポータル用バックエンド。稼働確認・サービス操作・
デプロイ（git pull）・nginx リロード・再起動・CEGコメント管理を行う。

セキュリティ方針:
- 127.0.0.1:8200 のみで待受。外部からは nginx の Basic認証の内側でしか到達できない。
- サービス名は ALLOWED、操作は ACTIONS の許可リストで検証。
- subprocess は配列実行（シェル無し）→ コマンドインジェクション不可。
- 特権操作は sudoers で当該コマンドのみ NOPASSWD 許可（server-admin/sudoers.tokusho-admin）。
- 自分自身（tokusho-admin）の stop / disable はロックアウト防止のためブロック。
"""
import os
import sqlite3
import subprocess
import time

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

# 操作を許可するサービス（systemd ユニット名 → 表示名）
ALLOWED = {
    "nginx": "Nginx",
    "cloudflared": "Cloudflare Tunnel",
    "ceg-comments": "CEG コメントAPI",
    "tokusho-admin": "管理API（自身）",
    # "smartlock-api": "SmartLock API",  # 実際のユニット名に合わせて有効化
}
ACTIONS = {"start", "stop", "restart", "enable", "disable"}
# サービスごとに禁止する操作（自分を止めると復帰不能になるため）
BLOCKED = {"tokusho-admin": {"stop", "disable"}}

REPO_DIR = os.environ.get("REPO_DIR", "/home/shodai/tokusho")
COMMENTS_DB = os.environ.get("COMMENTS_DB", "/home/shodai/data/ceg_comments.db")
MAX_LOG_LINES = 300

app = FastAPI(title="Tokusho Server Admin")


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
    # reboot はマシンごと落ちるため、応答を返してから発火させる
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


# ── CEGコメント管理（comments-api と同じSQLiteを直接参照） ──
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
