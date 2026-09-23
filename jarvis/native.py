"""Request narrowly scoped Accessibility actions from the signed launcher."""
import json
import os
import threading
import uuid

from .devlog import trace


class NativeActionError(RuntimeError):
    pass


class NativeBridge:
    def __init__(self):
        self._pending = {}
        self._lock = threading.Lock()

    def request(self, action: dict, timeout=6):
        if os.getenv("JARVIS_NATIVE_HOTKEY") != "1":
            raise NativeActionError("Visible interface control requires the Jarvis app")
        request_id = uuid.uuid4().hex
        event = threading.Event()
        slot = {"event": event, "response": None}
        with self._lock:
            self._pending[request_id] = slot
        payload = {"request_id": request_id, **action}
        trace("native.action_request", payload=payload)
        print("JARVIS_NATIVE_ACTION " + json.dumps(payload, ensure_ascii=False), flush=True)
        if not event.wait(timeout):
            with self._lock:
                self._pending.pop(request_id, None)
            raise NativeActionError("Jarvis could not verify the visible action")
        response = slot["response"] or {}
        trace("native.action_response", request_id=request_id, response=response)
        if not response.get("ok"):
            raise NativeActionError(response.get("error") or "Visible action failed")
        return response

    def receive(self, payload: dict):
        request_id = payload.get("request_id")
        with self._lock:
            slot = self._pending.pop(request_id, None)
        if slot is not None:
            slot["response"] = payload
            slot["event"].set()


bridge = NativeBridge()
