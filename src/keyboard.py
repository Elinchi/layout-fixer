"""evdev keycodes <-> us-layout characters, and a uinput keyboard to type with."""

import time

from evdev import UInput, ecodes as e

from layouts import US_LOWER, US_UPPER

# Physical keys in the order of layouts.US_LOWER / US_UPPER.
_KEYS = (
    ["KEY_GRAVE"] + [f"KEY_{n}" for n in "1234567890"] + ["KEY_MINUS", "KEY_EQUAL"]
    + [f"KEY_{c}" for c in "QWERTYUIOP"] + ["KEY_LEFTBRACE", "KEY_RIGHTBRACE", "KEY_BACKSLASH"]
    + [f"KEY_{c}" for c in "ASDFGHJKL"] + ["KEY_SEMICOLON", "KEY_APOSTROPHE"]
    + [f"KEY_{c}" for c in "ZXCVBNM"] + ["KEY_COMMA", "KEY_DOT", "KEY_SLASH"]
)
assert len(_KEYS) == len(US_LOWER)
KEYCODES = [getattr(e, k) for k in _KEYS]

# keycode -> (char without shift, char with shift)
CHAR_OF = {k: (lo, up) for k, lo, up in zip(KEYCODES, US_LOWER, US_UPPER)}
# us char -> (keycode, needs shift)
KEY_OF = {lo: (k, False) for k, lo in zip(KEYCODES, US_LOWER)}
KEY_OF.update({up: (k, True) for k, up in zip(KEYCODES, US_UPPER)})
KEY_OF[" "] = (e.KEY_SPACE, False)

SHIFTS = {e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT}
CTRLS = {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL}
ALTS = {e.KEY_LEFTALT, e.KEY_RIGHTALT}
METAS = {e.KEY_LEFTMETA, e.KEY_RIGHTMETA}
MODIFIERS = SHIFTS | CTRLS | ALTS | METAS

DEVICE_NAME = "layout-fixer virtual keyboard"


class Typist:
    """A virtual keyboard. It types *keys*, so the output follows the active layout."""

    DELAY = 0.001

    def __init__(self):
        # Every ordinary key, so keys queued during a grab can be replayed as-is.
        keys = set(range(e.KEY_ESC, e.KEY_MICMUTE + 1))
        self.ui = UInput({e.EV_KEY: sorted(keys)}, name=DEVICE_NAME)

    def _key(self, code, value):
        self.ui.write(e.EV_KEY, code, value)
        self.ui.syn()
        time.sleep(self.DELAY)

    def tap(self, code, *mods):
        for m in mods:
            self._key(m, 1)
        self._key(code, 1)
        self._key(code, 0)
        for m in reversed(mods):
            self._key(m, 0)

    def backspace(self, n):
        for _ in range(n):
            self.tap(e.KEY_BACKSPACE)

    def type_keys(self, keys: str):
        """Type a us-char key sequence ('ghbdsn'); unknown chars are skipped."""
        for ch in keys:
            if ch == "\n":
                self.tap(e.KEY_ENTER)
            elif ch in KEY_OF:
                code, shift = KEY_OF[ch]
                self.tap(code, *([e.KEY_LEFTSHIFT] if shift else []))

    def close(self):
        self.ui.close()
