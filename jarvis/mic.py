"""Async microphone capture backed by a sounddevice callback.

Audio stays in memory and is handed to the asyncio loop in bounded chunks. The
stream is stopped explicitly on push-to-talk release so the STT provider can
finalize the utterance instead of having its task cancelled.
"""
import asyncio
import audioop
from typing import Callable, Optional

from .devlog import trace

RATE = 16000
CHUNK = 1600  # 100 ms of 16 kHz mono PCM
_END = object()


class MicrophoneStream:
    """An async iterator of 16-bit mono PCM chunks."""

    def __init__(
        self,
        rate: int = RATE,
        chunk: int = CHUNK,
        device=None,
        on_status: Optional[Callable[[str], None]] = None,
        on_level: Optional[Callable[[float], None]] = None,
    ):
        self.rate = rate
        self.chunk = chunk
        self.device = device
        self.on_status = on_status
        self.on_level = on_level
        self._loop = None
        self._queue = None
        self._stream = None
        self._finished = False
        self._level_counter = 0

    async def __aenter__(self):
        import sounddevice as sd

        trace("microphone.opening", rate=self.rate, chunk=self.chunk, device=self.device)
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=50)
        self._stream = sd.RawInputStream(
            samplerate=self.rate,
            blocksize=self.chunk,
            device=self.device,
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
        )
        self._stream.start()
        trace("microphone.opened", rate=self.rate, chunk=self.chunk, device=self.device)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.finish()

    def _audio_callback(self, indata, frames, time_info, status):
        del frames, time_info
        if status and self.on_status:
            self._loop.call_soon_threadsafe(self.on_status, str(status))
        if not self._finished:
            self._level_counter += 1
            if self.on_level is not None and self._level_counter % 2 == 0:
                level = min(1.0, audioop.rms(indata, 2) / 4000.0)
                self._loop.call_soon_threadsafe(self.on_level, level)
            self._loop.call_soon_threadsafe(self._enqueue, bytes(indata))

    def _enqueue(self, chunk):
        if self._finished or self._queue is None:
            return
        if self._queue.full():
            # Avoid unbounded memory growth if networking stalls. Losing the
            # oldest 100 ms is preferable to blocking PortAudio's callback.
            self._queue.get_nowait()
        self._queue.put_nowait(chunk)

    def finish(self):
        """Stop capture and terminate async iteration. Safe to call repeatedly."""
        if self._finished:
            return
        self._finished = True
        trace("microphone.closing")
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._queue is not None:
            if self._queue.full():
                self._queue.get_nowait()
            self._queue.put_nowait(_END)
        trace("microphone.closed")

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._queue is None:
            raise RuntimeError("MicrophoneStream must be entered before iteration")
        item = await self._queue.get()
        if item is _END:
            raise StopAsyncIteration
        return item
