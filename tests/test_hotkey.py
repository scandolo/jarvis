from pynput import keyboard

from jarvis.hotkey import Hotkey


def test_only_right_option_matches():
    hotkey = Hotkey.__new__(Hotkey)
    hotkey._keyboard = keyboard
    assert hotkey._is_ropt(keyboard.Key.alt_r)
    assert not hotkey._is_ropt(keyboard.Key.alt_l)
    assert not hotkey._is_ropt(keyboard.Key.cmd_r)
