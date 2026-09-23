"""Jev System One client with full, key-safe developer tracing."""
import os
import time
import uuid

import httpx

from .devlog import trace
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

def decide(state: dict, questions: dict) -> dict:
    key = os.getenv("TYPESAFE_API_KEY", "")
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY missing in env")
    request_id = uuid.uuid4().hex
    payload = {"model": MODEL, "state": state, "questions": questions}
    trace("jev.request", request_id=request_id, url=API_URL, payload=payload)
    started = time.monotonic()
    try:
        resp = httpx.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=15,
        )
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        trace(
            "jev.response",
            request_id=request_id,
            status_code=resp.status_code,
            elapsed_ms=elapsed_ms,
            body=resp.text,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        trace(
            "jev.error",
            request_id=request_id,
            elapsed_ms=round((time.monotonic() - started) * 1000, 1),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
