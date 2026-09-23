"""Streaming speech-to-text clients.

Each client consumes an async iterator of PCM bytes and returns one finalized
utterance. Developer mode logs provider events and transcripts, but never audio
or API keys.
"""
import asyncio
import inspect
import json
import os
from typing import Awaitable, Callable, Optional, Union
from urllib.parse import urlencode

from .catalog import APPLICATIONS
from .devlog import trace

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


PartialCallback = Callable[[str, bool], Union[None, Awaitable[None]]]


class STTError(RuntimeError):
    pass


# Recognition hints, not command aliases or intent rules. Keep this focused on
# distinctive names; common nouns such as Notes can skew ordinary dictation.
SPEECH_APP_KEYS = ("arc", "chatgpt", "conductor", "notion", "notion_calendar", "claude")
SPEECH_KEYTERMS = tuple(APPLICATIONS[key].name for key in SPEECH_APP_KEYS) + ("Jarvis", "Jev")

def _redacted(name: str) -> str:
    return f"{name}={'set' if os.getenv(name) else 'MISSING'}"

def status() -> dict:
    return {"deepgram": _redacted("DEEPGRAM_API_KEY"), "assembly": _redacted("ASSEMBLYAI_API_KEY")}

async def _notify(callback: Optional[PartialCallback], text: str, is_final: bool):
    if callback is None:
        return
    result = callback(text, is_final)
    if inspect.isawaitable(result):
        await result


async def _run_connection(connect, url, headers, mic_chunks, close_message, receiver):
    async with connect(
        url,
        additional_headers=headers,
        open_timeout=10,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=20,
    ) as ws:
        async def sender():
            async for chunk in mic_chunks:
                await ws.send(chunk)
            await ws.send(json.dumps(close_message))

        send_task = asyncio.create_task(sender())
        receive_task = asyncio.create_task(receiver(ws))
        try:
            done, _ = await asyncio.wait(
                {send_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if receive_task in done and not send_task.done():
                # A provider closing before push-to-talk release is an error;
                # otherwise the mic producer would keep running forever.
                receive_task.result()
                raise STTError("Speech service closed before the utterance ended")
            await send_task
            try:
                return await asyncio.wait_for(receive_task, timeout=10)
            except asyncio.TimeoutError as exc:
                raise STTError("Speech service did not finalize the utterance") from exc
        finally:
            for task in (send_task, receive_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(send_task, receive_task, return_exceptions=True)


async def deepgram_stream(mic_chunks, on_partial: Optional[PartialCallback] = None):
    """Return finalized text from 16 kHz mono linear PCM audio."""
    from websockets.asyncio.client import connect

    key = os.getenv("DEEPGRAM_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY missing")
    parameters = [
        ("encoding", "linear16"), ("sample_rate", "16000"),
        ("channels", "1"), ("interim_results", "true"),
        ("smart_format", "true"), ("model", "nova-3"),
        ("language", "multi"), ("endpointing", "300"),
    ] + [("keyterm", term) for term in SPEECH_KEYTERMS]
    url = "wss://api.deepgram.com/v1/listen?" + urlencode(parameters)

    async def receiver(ws):
        final_parts = []
        latest_interim = ""
        async for msg in ws:
            try:
                data = json.loads(msg)
            except (TypeError, json.JSONDecodeError):
                trace("stt.provider_event_invalid", provider="deepgram", raw=str(msg))
                continue
            trace("stt.provider_event", provider="deepgram", data=data)
            if data.get("type") == "Error":
                raise STTError(data.get("description") or data.get("message") or "Deepgram error")
            alternatives = data.get("channel", {}).get("alternatives", [])
            text = alternatives[0].get("transcript", "").strip() if alternatives else ""
            if not text:
                continue
            is_final = bool(data.get("is_final"))
            if is_final:
                final_parts.append(text)
            else:
                latest_interim = text
            await _notify(on_partial, text, is_final)
        transcript = " ".join(final_parts).strip() or latest_interim
        trace("stt.final_transcript", provider="deepgram", transcript=transcript)
        return transcript

    trace("stt.connection_start", provider="deepgram", url=url)
    try:
        result = await _run_connection(
            connect,
            url,
            {"Authorization": f"Token {key}"},
            mic_chunks,
            {"type": "CloseStream"},
            receiver,
        )
        trace("stt.connection_end", provider="deepgram", transcript=result)
        return result
    except Exception as exc:
        trace("stt.error", provider="deepgram", error_type=type(exc).__name__, error=str(exc))
        raise

async def assembly_stream(mic_chunks, on_partial: Optional[PartialCallback] = None):
    from websockets.asyncio.client import connect

    key = os.getenv("ASSEMBLYAI_API_KEY", "")
    if not key:
        raise RuntimeError("ASSEMBLYAI_API_KEY missing")
    url = "wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&encoding=pcm_s16le"

    async def receiver(ws):
        final_parts = []
        latest_interim = ""
        async for msg in ws:
            try:
                data = json.loads(msg)
            except (TypeError, json.JSONDecodeError):
                trace("stt.provider_event_invalid", provider="assemblyai", raw=str(msg))
                continue
            trace("stt.provider_event", provider="assemblyai", data=data)
            message_type = data.get("type")
            if message_type in ("Error", "error"):
                raise STTError(data.get("error") or data.get("message") or "AssemblyAI error")
            if message_type not in ("PartialTranscript", "FinalTranscript"):
                continue
            text = data.get("text", "").strip()
            if not text:
                continue
            is_final = message_type == "FinalTranscript"
            if is_final:
                final_parts.append(text)
            else:
                latest_interim = text
            await _notify(on_partial, text, is_final)
        transcript = " ".join(final_parts).strip() or latest_interim
        trace("stt.final_transcript", provider="assemblyai", transcript=transcript)
        return transcript

    trace("stt.connection_start", provider="assemblyai", url=url)
    try:
        result = await _run_connection(
            connect,
            url,
            {"Authorization": key},
            mic_chunks,
            {"type": "Terminate"},
            receiver,
        )
        trace("stt.connection_end", provider="assemblyai", transcript=result)
        return result
    except Exception as exc:
        trace("stt.error", provider="assemblyai", error_type=type(exc).__name__, error=str(exc))
        raise

async def stream_with_fallback(mic_factory, on_partial=None, prefer="deepgram"):
    """Try both providers, creating a fresh audio iterator for each attempt."""
    order = [deepgram_stream, assembly_stream] if prefer == "deepgram" else [assembly_stream, deepgram_stream]
    errors = []
    for stream in order:
        try:
            return await stream(mic_factory(), on_partial)
        except Exception as exc:
            errors.append(f"{stream.__name__}: {exc}")
    raise STTError("; ".join(errors))
