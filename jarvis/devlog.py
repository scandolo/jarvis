"""Default-on structured developer tracing for Jarvis.

The trace intentionally contains transcripts and screen context. It never
contains microphone audio or API keys. Set JARVIS_DEVELOPER_MODE=0 to disable.
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


ENABLED = os.getenv("JARVIS_DEVELOPER_MODE", "1").lower() not in {"0", "false", "off"}
LOG_PATH = Path(os.getenv(
    "JARVIS_DEVELOPER_LOG",
    str(Path.home() / "Library/Logs/Jarvis/developer.jsonl"),
))
SESSION_ID = uuid.uuid4().hex
_LOCK = threading.Lock()
_MAX_BYTES = 10 * 1024 * 1024


def _rotate():
    if not LOG_PATH.exists() or LOG_PATH.stat().st_size < _MAX_BYTES:
        return
    previous = LOG_PATH.with_suffix(".previous.jsonl")
    if previous.exists():
        previous.unlink()
    LOG_PATH.replace(previous)


def trace(event: str, **data):
    if not ENABLED:
        return
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "monotonic": round(time.monotonic(), 6),
        "session_id": SESSION_ID,
        "event": event,
        **data,
    }
    with _LOCK:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate()
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


trace("session.started", developer_mode=ENABLED, pid=os.getpid())
