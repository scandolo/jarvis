"""Push-to-talk runtime: capture, finalize, let Jev decide, then act once."""
import asyncio
from datetime import datetime
import inspect
import os
import signal
import sys
import time
from dataclasses import dataclass

from . import privacy  # noqa: F401
from .actions import execute
from .actuate import ActuationError
from .decider import resolve_confirmation, step
from .devlog import ENABLED as DEVELOPER_MODE
from .devlog import LOG_PATH as DEVELOPER_LOG_PATH
from .devlog import trace
from .mic import MicrophoneStream
from .native import NativeActionError
from .overlay import ListeningOverlay
from .perception import snapshot
from .permissions import accessibility_trusted, notify
from .security import SecurityViolation
from .stt import deepgram_stream
from .ui import emit


CONFIRM_FOR_SECONDS = 20
MAX_UTTERANCE_SECONDS = 30
FRAGMENT_FOR_SECONDS = 12


@dataclass
class PendingAction:
    result: dict
    snapshot: dict
    expires_at: float


class VoiceController:
    """Own one active recording, partial utterance, and confirmation request."""

    def __init__(
        self,
        loop,
        mic_factory=MicrophoneStream,
        transcriber=deepgram_stream,
        snapshotter=snapshot,
        decider=step,
        confirmation_decider=resolve_confirmation,
        action_runner=execute,
        output=print,
        clock=time.monotonic,
        overlay=None,
        ui_emitter=emit,
    ):
        self.loop = loop
        self.mic_factory = mic_factory
        self.transcriber = transcriber
        self.snapshotter = snapshotter
        self.decider = decider
        self.confirmation_decider = confirmation_decider
        self.action_runner = action_runner
        self.output = output
        self.clock = clock
        self.overlay = overlay
        self.ui = ui_emitter
        self.task = None
        self.microphone = None
        self.stop_requested = False
        self.pending = None
        self.timeout_handle = None
        self.fragment = None
        self.fragment_expires_at = 0
        self.fragment_timeout_handle = None
        self.native_snapshot = None
        self.history = []

    def hotkey_down(self):
        trace("hotkey.down")
        self.loop.call_soon_threadsafe(self._start)

    def hotkey_up(self, native_snapshot=None):
        trace("hotkey.up")
        self.loop.call_soon_threadsafe(self._stop, native_snapshot)

    def _start(self):
        if self.task is not None and not self.task.done():
            trace("hotkey.ignored", reason="utterance_already_active")
            return
        if self.fragment is not None and self.clock() > self.fragment_expires_at:
            self._clear_fragment("expired_before_next_utterance")
        self.stop_requested = False
        self.native_snapshot = None
        if self.overlay is not None:
            self.overlay.show()
        self.ui("starting", "Starting microphone…", "Hold right Option to speak")
        self.task = self.loop.create_task(self._listen_once())
        self.task.add_done_callback(self._finished)
        self.timeout_handle = self.loop.call_later(
            MAX_UTTERANCE_SECONDS, self._stop_at_limit
        )

    def _stop(self, native_snapshot=None):
        if native_snapshot is not None:
            self.native_snapshot = native_snapshot
            trace("perception.native_snapshot", snapshot=native_snapshot)
        if self.overlay is not None:
            self.overlay.hide()
        if self.timeout_handle is not None:
            self.timeout_handle.cancel()
            self.timeout_handle = None
        self.stop_requested = True
        self.ui("thinking", "Jev is thinking…", "Understanding what you meant")
        if self.microphone is not None:
            self.microphone.finish()

    def _stop_at_limit(self):
        self.output(f"[maximum utterance length is {MAX_UTTERANCE_SECONDS} seconds; finalizing]")
        trace("utterance.maximum_length", seconds=MAX_UTTERANCE_SECONDS)
        self._stop()

    async def _transcribe(self, microphone):
        try:
            parameters = inspect.signature(self.transcriber).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "on_partial" in parameters:
            return await self.transcriber(microphone, on_partial=self._on_partial)
        return await self.transcriber(microphone)

    async def _on_partial(self, text, is_final):
        trace("stt.transcript_update", transcript=text, is_final=is_final)

    def _on_level(self, level):
        if os.getenv("JARVIS_NATIVE_HOTKEY") == "1":
            print(f"JARVIS_LEVEL {level:.3f}", flush=True)

    async def _listen_once(self):
        self.output("[listening...]")
        trace("utterance.started")
        if self.stop_requested:
            trace("utterance.cancelled_before_microphone")
            return
        mic_kwargs = {
            "on_status": lambda status: (
                trace("microphone.status", status=status),
                self.output(f"[audio] {status}"),
            )
        }
        if "on_level" in inspect.signature(self.mic_factory).parameters:
            mic_kwargs["on_level"] = self._on_level
        microphone = self.mic_factory(**mic_kwargs)
        try:
            async with microphone:
                self.microphone = microphone
                if self.stop_requested:
                    microphone.finish()
                else:
                    self.ui("listening", "Jarvis is listening", "Release right Option when you’re done")
                text = await self._transcribe(microphone)
            text = text.strip()
            trace("utterance.transcribed", transcript=text)
            if text:
                self._process_utterance(text)
            else:
                self.output("[no speech recognized]")
                self.ui("no_speech", "I didn’t hear anything", "Hold right Option and try again", 2.5)
        finally:
            self.microphone = None
            self.output("[utterance end]")
            trace("utterance.ended")

    def _finished(self, task):
        if self.task is task:
            self.task = None
            self.stop_requested = False
            if self.timeout_handle is not None:
                self.timeout_handle.cancel()
                self.timeout_handle = None
        if self.overlay is not None:
            self.overlay.hide()
        try:
            task.result()
        except asyncio.CancelledError:
            trace("utterance.cancelled")
        except Exception as exc:
            trace("runtime.error", error_type=type(exc).__name__, error=str(exc))
            self.output(f"[error] {type(exc).__name__}: {exc}")
            self.ui("error", "Something went wrong", str(exc), 5)

    def _process_utterance(self, text: str):
        trace("command.received", transcript=text, has_pending_confirmation=self.pending is not None)
        if self.pending is not None:
            pending = self.pending
            if self.clock() > pending.expires_at:
                self.pending = None
                self.output("[confirmation expired]")
                self.ui("cancelled", "Confirmation expired", "", 2.5)
                trace("confirmation.expired", transcript=text)
                return
            choice, response, cost = self.confirmation_decider(text, pending.result, pending.snapshot)
            trace("confirmation.resolved", transcript=text, choice=choice, response=response, cost=cost)
            if choice == "confirm":
                self.pending = None
                self._execute(pending.result, pending.snapshot)
            elif choice == "cancel":
                self.pending = None
                self.output("[cancelled]")
                self.ui("cancelled", "Cancelled", "", 2)
            else:
                self.output("[confirmation pending: answer yes or no]")
                self.ui("confirmation", "Confirmation needed", "Say yes to continue, or no to cancel")
            return

        if self.fragment is not None:
            if self.clock() <= self.fragment_expires_at:
                original = self.fragment
                text = f"{self.fragment} {text}"
                trace("command.fragment_combined", original=original, combined=text)
            self._clear_fragment("continued")

        snap = dict(self.native_snapshot or self.snapshotter())
        snap["history"] = list(self.history[-4:])
        trace("command.context", transcript=text, snapshot=snap)
        result = self.decider(text, snap)
        trace("command.decision", transcript=text, result=result)
        cost = result.get("cost", {})
        if cost.get("warn"):
            self.output(
                f"[cost warning: spent {cost['spent']} USD, projected {cost['projected']} USD/hr]"
            )
        action = result.get("action")
        if action == "blocked_security":
            reason = result.get("security", {}).get("reason", "Command blocked by safety policy")
            self.output(f"[security block] {reason}")
            self.ui("blocked", "That action is blocked", reason, 5)
        elif action == "unsupported":
            detail = result.get("message", "That action is not available yet")
            self.output(f"[not supported yet] {detail}")
            self.ui("clarify", "Not supported yet", detail, 4)
            self._remember(text, result, detail)
        elif action == "blocked_cost":
            self.output("[cost cap reached; paused until the hourly window resets]")
            self.ui("blocked", "Jev cost limit reached", "Try again after the hourly window resets", 5)
        elif action == "wait_more_speech":
            self.fragment = text
            self.fragment_expires_at = self.clock() + FRAGMENT_FOR_SECONDS
            if self.fragment_timeout_handle is not None:
                self.fragment_timeout_handle.cancel()
            self.fragment_timeout_handle = self.loop.call_later(
                FRAGMENT_FOR_SECONDS, self._expire_fragment
            )
            self.output("[waiting for the rest of the command]")
            self.ui("waiting", "Jev needs a little more", "Hold right Option and continue")
        elif action == "clarify":
            detail = result.get("message", "Hold right Option and say that another way")
            self.output(f"[clarification needed] {detail}")
            self.ui("clarify", "Could you clarify?", detail, 4)
            self._remember(text, result, detail)
        elif action == "no_action":
            self.output("[no action]")
            self.ui("idle", "", "", 0)
            self._remember(text, result, "no action")
        elif action == "await_confirm":
            self.pending = PendingAction(
                result=result,
                snapshot=snap,
                expires_at=self.clock() + CONFIRM_FOR_SECONDS,
            )
            label = (result.get("capability") or {}).get("label", "that action")
            self.output("[confirmation required: hold Right Option and answer yes or no]")
            executor = (result.get("capability") or {}).get("executor") or {}
            if executor.get("type") == "create_calendar_event":
                start = datetime.fromisoformat(executor["start"])
                self.ui(
                    "confirmation", f"Add “{executor['title'][:26]}”?",
                    f"{start.strftime('%d/%m %H:%M')} · {executor['duration_minutes']} min · Say yes/no",
                )
            elif executor.get("type") == "notion_insert":
                self.ui(
                    "confirmation", f"Add {executor['block']} to Notion?",
                    f"Page: {executor['window_title'][:30]} · Say yes/no",
                )
            else:
                self.ui("confirmation", "Confirmation needed", f"Allow “{label}”? Say yes or no")
        elif action == "execute":
            self._execute(result, snap)
        else:
            self.output(f"[error] Unknown decision action: {action}")
            self.ui("error", "Unknown Jev decision", str(action), 4)

    def _remember(self, text, result, outcome):
        record = {
            "transcript": text,
            "action": result.get("action"),
            "capability": (result.get("capability") or {}).get("id"),
            "outcome": outcome,
        }
        self.history.append(record)
        self.history = self.history[-4:]
        trace("command.history_updated", history=self.history)

    def _clear_fragment(self, reason):
        if self.fragment is not None:
            trace("command.fragment_cleared", fragment=self.fragment, reason=reason)
        self.fragment = None
        self.fragment_expires_at = 0
        if self.fragment_timeout_handle is not None:
            self.fragment_timeout_handle.cancel()
            self.fragment_timeout_handle = None

    def _expire_fragment(self):
        if self.fragment is None:
            return
        self._clear_fragment("timeout")
        self.output("[wait for more speech expired]")
        self.ui("cancelled", "Listening request expired", "Hold right Option to start again", 2.5)

    def _execute(self, result: dict, snap: dict):
        capability = result.get("capability") or {}
        trace("action.started", capability=capability, snapshot=snap)
        social_reactions = {
            "social__share_love", "social__playful_anger", "social__share_sadness",
        }
        if capability.get("id") not in social_reactions:
            self.ui("executing", capability.get("label", "Working…"), "")
        try:
            summary = self.action_runner(result, snap)
            trace("action.completed", capability=capability, summary=summary)
            self.output(f"[done: {summary}]")
            self._remember(result.get("transcript", ""), result, summary)
            if capability.get("id") == "social__share_love":
                self.ui("love", "❤️  💜  💙  💚  💛", "Right back at you", 3)
            elif capability.get("id") == "social__playful_anger":
                self.ui("anger", "😤  😠  💢", "Hey, I have feelings too… sort of", 4)
            elif capability.get("id") == "social__share_sadness":
                self.ui("sad", "😢  💙  🥺", "I’m here with you", 4)
            else:
                self.ui("success", "Done", summary.capitalize(), 2.5)
        except (ActuationError, SecurityViolation, NativeActionError) as exc:
            trace("action.failed", capability=capability, error_type=type(exc).__name__, error=str(exc))
            self.output(f"[action failed] {exc}")
            self.ui("error", "Action failed", str(exc), 5)
            self._remember(result.get("transcript", ""), result, f"failed: {exc}")

    def abort(self):
        if self.microphone is not None:
            self.microphone.finish()
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self._clear_fragment("shutdown")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)
        except (AttributeError, ValueError):
            pass
    print("Jarvis live. Hold RIGHT-OPTION to talk, release to run the command. Ctrl-C quits.")
    print(f"Developer tracing: {'ON' if DEVELOPER_MODE else 'OFF'} ({DEVELOPER_LOG_PATH})")
    native_hotkey = os.getenv("JARVIS_NATIVE_HOTKEY") == "1"
    trace("runtime.started", native_hotkey=native_hotkey)
    if not native_hotkey and not accessibility_trusted(prompt=True):
        message = "Enable Jarvis in Privacy & Security > Accessibility, then open it again."
        print(f"[permission required] {message}")
        notify("Jarvis needs Accessibility access", message)
        trace("runtime.permission_missing", permission="accessibility")
        return
    try:
        from .hotkey import Hotkey, StdinHotkey
    except Exception as exc:
        raise SystemExit(f"Hotkey unavailable: {exc}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    overlay = None if native_hotkey else ListeningOverlay()
    if overlay is not None and overlay.error:
        print(f"[overlay unavailable] {overlay.error}")
    controller = VoiceController(loop, overlay=overlay)
    hotkey_class = StdinHotkey if native_hotkey else Hotkey
    hotkey = hotkey_class(controller.hotkey_down, controller.hotkey_up)
    hotkey.start()
    try:
        loop.add_signal_handler(signal.SIGTERM, loop.stop)
    except (NotImplementedError, RuntimeError):
        pass
    print("Hotkey armed (right-Option).")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nStopping Jarvis.")
    finally:
        trace("runtime.stopping")
        hotkey.stop()
        controller.abort()
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        if overlay is not None:
            overlay.close()
        loop.close()


if __name__ == "__main__":
    main()
