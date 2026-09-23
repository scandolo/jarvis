import asyncio
import json
from urllib.parse import parse_qs, urlparse

from jarvis import stt


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed_by_client = asyncio.Event()
        self.messages = None

    async def send(self, value):
        self.sent.append(value)
        if isinstance(value, str) and json.loads(value).get("type") == "CloseStream":
            self.closed_by_client.set()

    def __aiter__(self):
        self.messages = self._messages()
        return self.messages

    async def __anext__(self):
        return await self.messages.__anext__()

    async def _messages(self):
        await self.closed_by_client.wait()
        yield json.dumps({
            "type": "Results",
            "is_final": True,
            "channel": {"alternatives": [{"transcript": "open notes"}]},
        })


class FakeConnection:
    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_deepgram_uses_websockets_15_headers_and_finalizes(monkeypatch):
    async def scenario():
        websocket = FakeWebSocket()
        call = {}

        def connect(url, **kwargs):
            call.update({"url": url, **kwargs})
            return FakeConnection(websocket)

        async def chunks():
            yield b"pcm"

        monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key")
        monkeypatch.setattr("websockets.asyncio.client.connect", connect)
        text = await stt.deepgram_stream(chunks())
        assert text == "open notes"
        assert call["additional_headers"] == {"Authorization": "Token test-key"}
        query = parse_qs(urlparse(call["url"]).query)
        assert query["language"] == ["multi"]
        assert "Arc" in query["keyterm"]
        assert "ChatGPT" in query["keyterm"]
        assert "Conductor" in query["keyterm"]
        assert json.loads(websocket.sent[-1]) == {"type": "CloseStream"}

    asyncio.run(scenario())
