import asyncio

from jarvis.live import VoiceController


def _result(action="execute", capability_id="app__notes"):
    result = {
        "action": action,
        "cost": {"warn": False, "blocked": False},
        "transcript": "open notes",
    }
    if action in {"execute", "await_confirm"}:
        result["capability"] = {
            "id": capability_id,
            "label": "Open Notes",
            "effects": ("launch_application",),
            "executor": {
                "type": "open_bundle",
                "bundle_id": "com.apple.Notes",
                "name": "Notes",
            },
            "requires_confirmation": action == "await_confirm",
        }
    return result


class FakeMicrophone:
    def __init__(self, on_status=None):
        self.on_status = on_status
        self.finished = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.finish()

    def finish(self):
        self.finished.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.finished.wait()
        raise StopAsyncIteration


def test_release_finalizes_before_action_and_updates_ui():
    async def scenario():
        actions = []
        states = []

        async def transcribe(microphone):
            async for _ in microphone:
                pass
            return "open notes"

        loop = asyncio.get_running_loop()
        controller = VoiceController(
            loop,
            mic_factory=FakeMicrophone,
            transcriber=transcribe,
            snapshotter=lambda: {"elements": []},
            decider=lambda text, snap: _result(),
            action_runner=lambda result, snap: actions.append(result) or "opened notes",
            output=lambda message: None,
            ui_emitter=lambda state, title, detail="", duration=None: states.append(state),
        )
        controller._start()
        task = controller.task
        await asyncio.sleep(0)
        assert actions == []
        assert states[-1] == "listening"
        controller._stop()
        assert states[-1] == "thinking"
        await task
        assert len(actions) == 1
        assert states[-1] == "success"

    asyncio.run(scenario())


def test_release_before_task_start_never_opens_microphone():
    async def scenario():
        created = []

        def mic_factory(on_status=None):
            created.append(True)
            return FakeMicrophone(on_status)

        loop = asyncio.get_running_loop()
        controller = VoiceController(
            loop,
            mic_factory=mic_factory,
            output=lambda message: None,
            ui_emitter=lambda *args: None,
        )
        controller._start()
        task = controller.task
        controller._stop()
        await task
        assert created == []

    asyncio.run(scenario())


def test_confirmation_uses_jev_and_executes_original_action():
    actions = []
    outputs = []
    states = []
    loop = asyncio.new_event_loop()
    try:
        controller = VoiceController(
            loop,
            snapshotter=lambda: {"elements": []},
            decider=lambda text, snap: _result("await_confirm"),
            confirmation_decider=lambda text, result, snap: ("confirm", {"answers": {}}, {}),
            action_runner=lambda result, snap: actions.append(result) or "opened notes",
            output=outputs.append,
            clock=lambda: 100,
            ui_emitter=lambda state, title, detail="", duration=None: states.append(state),
        )
        controller._process_utterance("do something")
        assert controller.pending is not None
        assert states[-1] == "confirmation"
        controller._process_utterance("yes please")
        assert controller.pending is None
        assert len(actions) == 1
        assert outputs[-1] == "[done: opened notes]"
    finally:
        loop.close()


def test_confirmation_can_be_cancelled():
    actions = []
    loop = asyncio.new_event_loop()
    try:
        controller = VoiceController(
            loop,
            snapshotter=lambda: {"elements": []},
            decider=lambda text, snap: _result("await_confirm"),
            confirmation_decider=lambda text, result, snap: ("cancel", None, {}),
            action_runner=lambda result, snap: actions.append(result),
            output=lambda message: None,
            clock=lambda: 100,
            ui_emitter=lambda *args: None,
        )
        controller._process_utterance("do something")
        controller._process_utterance("no thanks")
        assert controller.pending is None
        assert actions == []
    finally:
        loop.close()


def test_incomplete_utterances_are_combined_and_visible():
    decisions = []
    actions = []
    states = []
    loop = asyncio.new_event_loop()
    try:
        def decide(text, snap):
            decisions.append(text)
            return _result("wait_more_speech" if len(decisions) == 1 else "execute")

        controller = VoiceController(
            loop,
            snapshotter=lambda: {"elements": []},
            decider=decide,
            action_runner=lambda result, snap: actions.append(result) or "opened Arc",
            output=lambda message: None,
            clock=lambda: 100,
            ui_emitter=lambda state, title, detail="", duration=None: states.append(state),
        )
        controller._process_utterance("open")
        assert states[-1] == "waiting"
        controller._process_utterance("arc browser")
        assert decisions == ["open", "open arc browser"]
        assert len(actions) == 1
    finally:
        controller._clear_fragment("test_cleanup")
        loop.close()


def test_love_action_shows_hearts():
    states = []
    loop = asyncio.new_event_loop()
    try:
        controller = VoiceController(
            loop,
            snapshotter=lambda: {},
            decider=lambda text, snap: _result("execute", "social__share_love"),
            action_runner=lambda result, snap: "shared some love",
            output=lambda message: None,
            ui_emitter=lambda state, title, detail="", duration=None: states.append(
                (state, title, detail)
            ),
        )
        controller._process_utterance("thank you")
        assert states[-1][0] == "love"
        assert "❤️" in states[-1][1]
    finally:
        loop.close()
