import hashlib, uuid, os
from datetime import datetime, timedelta, timezone

SESSION_HOURS = 8

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def new_session_token() -> str:
    return str(uuid.uuid4())

def session_expires() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()

def is_expired(dt_str) -> bool:
    if dt_str is None:
        return False
    dt = dt_str if hasattr(dt_str, 'tzinfo') else datetime.fromisoformat(str(dt_str))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < datetime.now(timezone.utc)
