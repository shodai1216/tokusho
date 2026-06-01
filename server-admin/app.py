"""Tokusho サーバー管理API（FastAPI）

apex（tokusho.org）の管理ポータルから、サーバーの稼働状況確認・
許可サービスの再起動・ログ閲覧を行うための小さなAPI。

セキュリティ方針:
- 127.0.0.1:8200 のみで待受。外部からは nginx の Basic認証の内側でしか到達できない。
- 操作対象は ALLOWED の許可リストのみ。サービス名はキー照合で検証する。
- subprocess は配列で実行（シェルを介さない）→ コマンドインジェクション不可。
- 特権操作（restart / journalctl）は sudoers で当該コマンドのみ NOPASSWD 許可する。
  ブランケットな sudo 権限は付与しない（server-admin/sudoers.tokusho-admin 参照）。
"""
import shutil
import subprocess
import time

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

# 操作を許可するサービス（systemd ユニット名 → 表示名）
# 実在しないユニットを足すと is-active が unknown になるだけ。実環境に合わせて編集。
ALLOWED = {
    "nginx": "Nginx",
    "cloudflared": "Cloudflare Tunnel",
    "ceg-comments": "CEG コメントAPI",
    "tokusho-admin": "管理API（自身）",
    # "smartlock-api": "SmartLock API",  # 実際のユニット名に合わせて有効化
}
MAX_LOG_LINES = 300

app = FastAPI(title="Tokusho Server Admin")


def run(cmd, timeout=10):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def is_active(svc: str) -> str:
    try:
        r = run(["systemctl", "is-active", svc], timeout=5)
        return r.stdout.strip() or "unknown"
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
    services = [
        {"id": k, "label": v, "active": is_active(k)} for k, v in ALLOWED.items()
    ]
    return {
        "services": services,
        "system": system_info(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


class RestartIn(BaseModel):
    service: str


@app.post("/restart")
def restart(payload: RestartIn):
    svc = payload.service
    if svc not in ALLOWED:
        raise HTTPException(status_code=400, detail="service not allowed")
    try:
        r = run(["sudo", "-n", "systemctl", "restart", svc], timeout=30)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="restart timed out")
    ok = r.returncode == 0
    return {
        "ok": ok,
        "service": svc,
        "active": is_active(svc),
        "message": "restarted" if ok else (r.stderr.strip() or r.stdout.strip())[:500],
    }


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
        raise HTTPException(
            status_code=500, detail=(r.stderr.strip() or "journalctl failed")[:500]
        )
    return {"service": service, "lines": r.stdout.splitlines()[-lines:]}
