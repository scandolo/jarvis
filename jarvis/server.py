"""FastAPI server: /step takes live transcript, runs Jev tree, executes or gates.
STT (Deepgram/Assembly) streams in separately and POSTs partials here.
Hotkey (right-Option push-to-talk) TODO via pynput/CGEvent tap.
"""
from fastapi import FastAPI
from pydantic import BaseModel
from . import privacy  # noqa: F401 — installs redacting log filter
from .actions import execute
from .perception import snapshot
from .decider import step

app = FastAPI(title="Jarvis v1")

class Transcript(BaseModel):
    text: str
    is_final: bool = True

@app.post("/step")
def do_step(t: Transcript):
    if not t.is_final:
        return {"action": "wait_for_final"}
    snap = snapshot()
    res = step(t.text, snap)
    if res["action"] == "execute":
        res["execution"] = execute(res, snap)
    return res

@app.get("/health")
def health(): return {"ok": True}
