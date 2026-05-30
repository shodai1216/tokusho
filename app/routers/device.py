import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.database import get_db

router = APIRouter()
TOKEN = os.getenv("TOKEN")

class DeviceReport(BaseModel):
    token: str
    state: str = "unknown"
    door:  str = "unknown"
    thumb: str = "unknown"
    error: str = ""

@router.post("/smartlock")
def receive_report(body: DeviceReport):
    if body.token != TOKEN:
        raise HTTPException(401, "unauthorized")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE device_status
                SET state=%s, door=%s, thumb=%s, error=%s, last_updated=NOW()
                WHERE id=1
            """, (body.state, body.door, body.thumb, body.error))

            cur.execute(
                "INSERT INTO logs (state, door, thumb, error) VALUES (%s,%s,%s,%s)",
                (body.state, body.door, body.thumb, body.error)
            )

            cur.execute(
                "SELECT id, command FROM commands WHERE status='pending' ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
            cmd = "none"
            if row:
                cur.execute("UPDATE commands SET status='done' WHERE id=%s", (row["id"],))
                cmd = row["command"]

    return {"status": "ok", "command": cmd}
