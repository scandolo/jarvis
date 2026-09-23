import ctypes

import pytest

from jarvis import actuate
from jarvis.actuate import ActuationError


class FakeDisplay:
    def __init__(self, value):
        self.value = value
        self.set_values = []
        self.reverse = False

    def DisplayServicesGetBrightness(self, display_id, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_float)).contents.value = self.value
        return 0

    def DisplayServicesSetBrightness(self, display_id, value):
        self.set_values.append(value.value)
        self.value = 1 - value.value if self.reverse else value.value
        return 0


def test_brightness_decrease_reads_back_direction(monkeypatch):
    display = FakeDisplay(0.5)
    monkeypatch.setattr(actuate, "_display_services", lambda: (1, display))
    summary = actuate.adjust_brightness(-1)
    assert display.set_values[0] < 0.5
    assert summary == "brightness 44%"


def test_brightness_wrong_direction_fails(monkeypatch):
    display = FakeDisplay(0.5)
    display.reverse = True
    monkeypatch.setattr(actuate, "_display_services", lambda: (1, display))
    with pytest.raises(ActuationError, match="requested direction"):
        actuate.adjust_brightness(-1)
