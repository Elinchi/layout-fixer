"""Typing state machine: follows physical keys, decides, retypes.

Device-free on purpose; daemon.py feeds it events and tests feed it fakes.
Text is tracked as *keys* (us-layout chars), so retyping a word in the other
layout means: Backspace over it, switch layout, type the same keys again.
"""

import re
import time
from collections import deque

from evdev import ecodes as e

from keyboard import ALTS, CHAR_OF, CTRLS, KEY_OF, METAS, MODIFIERS, SHIFTS
from layouts import UK_LETTERS, to_keys, to_uk
from model import decide, decide_prefix

OTHER = {"en": "uk", "uk": "en"}
MAX_BUF = 200
MOD_CLASS = {**{k: "shift" for k in SHIFTS}, **{k: "ctrl" for k in CTRLS},
             **{k: "alt" for k in ALTS}, **{k: "super" for k in METAS}}
MOD_ORDER = ("ctrl", "alt", "super", "shift")


def key_name(code: int) -> str:
    name = e.KEY.get(code, "")
    if isinstance(name, list):
        name = name[0]
    return name.removeprefix("KEY_").lower()


def normalize_hotkey(spec: str) -> str:
    spec = spec.strip().lower()
    if spec.startswith("double:") or spec in ("", "none"):
        return spec
    *mods, key = spec.split("+")
    return "+".join([m for m in MOD_ORDER if m in mods] + [key])


class Engine:
    def __init__(self, model, cfg, learned, typist, layout, clipboard, notify, save_cfg, save_learned):
        self.model, self.typist, self.layout, self.clipboard = model, typist, layout, clipboard
        self.notify, self._save_cfg, self._save_learned = notify, save_cfg, save_learned
        self.buf: list[str] = []
        self.version = 0
        self.device = None
        self.held: set[int] = set()
        self.last_fix = None
        self.pending = None
        self.tap_key = None
        self.last_tap = None
        self.window_class = ""
        self.fullscreen = False
        self.game = False
        self.window_id = None
        self.typed_at = 0.0
        self.selection_at = None
        self.log = deque(maxlen=200)   # decisions, kept in memory only
        self.configure(cfg, learned)

    # ---- configuration --------------------------------------------------
    def configure(self, cfg, learned):
        self.cfg, self.learned = cfg, learned
        self.hotkeys = {}
        for action, spec in cfg["hotkeys"].items():
            spec = normalize_hotkey(spec)
            if spec not in ("", "none"):
                self.hotkeys[spec] = action
        self.exclude = [re.compile(p) for p in cfg["exclude"]]
        self.games = [re.compile(p) for p in cfg.get("games", [])]
        self.model.user = {"keep": set(learned["keep"]), "switch": set(learned["switch"])}

    def auto_allowed(self) -> bool:
        if self.game:
            return False
        if self.fullscreen and not self.cfg["auto_in_fullscreen"]:
            return False
        return not any(p.fullmatch(self.window_class) for p in self.exclude)

    # ---- events ---------------------------------------------------------
    def reset(self, why=""):
        self.buf.clear()
        self.version += 1
        self.last_fix = None
        self.pending = None

    def on_window(self, cls, fullscreen, game=False, window_id=None):
        self.window_class, self.fullscreen = cls, fullscreen
        self.game = game or any(p.fullmatch(cls) for p in self.games)
        # Title changes (spinners in Codex/Claude redraw ~10x/s) also fire
        # "activewindow"; only a different window means the text is elsewhere.
        if window_id is None or window_id != self.window_id:
            self.window_id = window_id
            self.reset("window")

    def on_selection(self, now=None):
        self.selection_at = now or time.monotonic()

    def on_key(self, code, value, device, now=None):
        now = now or time.monotonic()
        if value == 1:
            self.held.add(code)
        elif value == 0:
            self.held.discard(code)
        if code in MODIFIERS:
            self._modifier(code, value, now)
            return
        if value == 0:
            return
        self.tap_key = self.last_tap = None
        mods = {MOD_CLASS[k] for k in self.held if k in MODIFIERS}
        if value == 1:
            spec = "+".join([m for m in MOD_ORDER if m in mods] + [key_name(code)])
            if spec in self.hotkeys:
                self.trigger(self.hotkeys[spec])
                return
        if mods - {"shift"}:
            self.reset("shortcut")
            return
        if code == e.KEY_BACKSPACE:
            if self.buf:
                self.buf.pop()
                self.version += 1
            return
        if code == e.KEY_SPACE:
            self._append(" ", device, now)
            self._word_end()
            return
        if code in CHAR_OF:
            self._append(CHAR_OF[code][1 if "shift" in mods else 0], device, now)
            self._early()
            return
        self.reset("navigation")

    def _modifier(self, code, value, now):
        if value == 1:
            others = self.held - {code}
            self.tap_key = code if not others else None
        elif value == 0 and code == self.tap_key:
            self.tap_key = None
            cls = MOD_CLASS[code]
            last = self.last_tap
            if last and last[0] == cls and (now - last[1]) * 1000 <= self.cfg["double_tap_ms"]:
                self.last_tap = None
                action = self.hotkeys.get("double:" + cls)
                if action:
                    self.trigger(action)
            else:
                self.last_tap = (cls, now)

    def _append(self, ch, device, now):
        self.buf.append(ch)
        self.version += 1
        self.device, self.typed_at = device, now
        if len(self.buf) > MAX_BUF:
            del self.buf[:len(self.buf) - MAX_BUF]
            self.last_fix = None

    # ---- auto mode ------------------------------------------------------
    def _word_end(self):
        if self.cfg["mode"] == "manual" or not self.auto_allowed():
            return
        end = len(self.buf) - 1                  # index of the space just typed
        start = end
        while start > 0 and self.buf[start - 1] != " ":
            start -= 1
        word = "".join(self.buf[start:end])
        lang = self.layout.lang(self.device)
        if not word or not lang:
            return
        d = decide(word, lang, self.model)
        if self.cfg["mode"] == "log":
            shown = word if lang == "en" else to_uk(word)
            self.log.append(f"{shown!r} [{lang}] -> {'SWITCH' if d.switch else 'keep'} ({d.reason})")
            return
        if d.switch:
            # Run once no key is held (see daemon); the user may type on meanwhile.
            expect = word + " "
            self.pending = lambda: self._auto_fix(start, expect, lang)

    def _early(self):
        """Fix a word while it is still being typed, when the start already
        settles it (vjle... = моду...): then Enter or a closing quote right
        after the word is fine too. The space check still runs afterwards."""
        if self.cfg["mode"] != "auto" or self.pending or not self.auto_allowed():
            return
        start = len(self.buf)
        while start > 0 and self.buf[start - 1] != " ":
            start -= 1
        if self.last_fix and self.last_fix["start"] >= start:
            return                                # this word was fixed (or undone) already
        run = "".join(self.buf[start:])
        lang = self.layout.lang(self.device)
        offset = decide_prefix(run, lang, self.model) if lang else None
        if offset is not None:
            start += offset                       # keep an opening quote as it is
            self.pending = lambda: self._auto_fix(start, run[offset:], lang)

    def _auto_fix(self, start, expect, lang):
        if "".join(self.buf[start:start + len(expect)]) != expect:
            return                                # edited meanwhile: leave it alone
        self._retype(start, OTHER[lang], auto=True, word=expect.strip())

    # ---- actions --------------------------------------------------------
    def trigger(self, action):
        if self.game:
            return
        fn = {"fix_last": self.fix_last, "fix_selection": self.fix_selection,
              "toggle_auto": self.toggle_auto}.get(action)
        if fn:
            self.pending = fn

    def run_pending(self):
        fn, self.pending = self.pending, None
        if fn:
            fn()

    def _retype(self, start, to_lang, auto, word):
        """Erase buf[start:] on screen and type the same keys in `to_lang`."""
        tail = "".join(self.buf[start:])
        from_lang = OTHER[to_lang]
        self.typist.backspace(len(tail))
        self.layout.switch(to_lang)
        self.typist.type_keys(tail)
        self.last_fix = {"start": start, "from": from_lang, "to": to_lang, "auto": auto,
                         "word": word, "version": self.version}
        if auto:
            self.log.append(f"auto: {word!r} {from_lang}->{to_lang}")

    def fix_last(self):
        end = len(self.buf)
        while end > 0 and self.buf[end - 1] == " ":
            end -= 1
        start = end
        while start > 0 and self.buf[start - 1] != " ":
            start -= 1
        fix = self.last_fix
        if fix and not fix.get("undone") and start <= fix["start"] < max(end, start + 1):
            # The last word was just fixed (maybe after a few letters, typed on since):
            # the hotkey undoes it, and an auto fix is remembered for the whole word.
            word = "".join(self.buf[fix["start"]:end]) or fix["word"]
            self._retype(fix["start"], fix["from"], auto=False, word=word)
            if fix["auto"]:
                self._learn("keep", fix["from"], word)
            self.last_fix["undone"] = True
            return
        lang = self.layout.lang(self.device)
        if start == end or not lang:
            self.notify("Нема що виправляти: слово не набране після останнього кліку")
            return
        word = "".join(self.buf[start:end])
        self._retype(start, OTHER[lang], auto=False, word=word)
        self._learn_manual(lang, word)

    def fix_selection(self):
        if self.selection_at is None or self.selection_at < self.typed_at:
            self.notify("Спочатку виділіть текст")
            return
        text = self.clipboard.primary()
        self.selection_at = None
        if not text:
            return
        cyr = sum(c.lower() in UK_LETTERS for c in text)
        lat = sum(c.isascii() and c.isalpha() for c in text)
        to = "en" if cyr > lat else "uk"
        keys = to_keys(text) if to == "en" else text
        if "\n" not in keys and all(c in KEY_OF for c in keys):
            self.layout.switch(to)
            self.typist.type_keys(keys)       # typing replaces the selection
        else:
            self.clipboard.paste(keys if to == "en" else to_uk(keys), self.window_class)
            self.layout.switch(to)
        self.reset("selection")

    def toggle_auto(self):
        self.cfg["mode"] = "manual" if self.cfg["mode"] == "auto" else "auto"
        self._save_cfg(self.cfg)
        self.notify("Автоматичне виправлення " + ("увімкнено" if self.cfg["mode"] == "auto"
                                                 else "вимкнено (лише хоткей)"))

    # ---- learning -------------------------------------------------------
    def _learn(self, kind, lang, keys):
        if not self.cfg["learn"] or not keys:
            return
        item = f"{lang}:{keys.lower()}"
        other = "switch" if kind == "keep" else "keep"
        if item in self.learned[other]:
            self.learned[other].remove(item)
        if item not in self.learned[kind]:
            self.learned[kind].append(item)
        self.model.user = {"keep": set(self.learned["keep"]), "switch": set(self.learned["switch"])}
        self._save_learned(self.learned)
        if kind == "keep":
            shown = keys if lang == "en" else to_uk(keys)
            self.notify(f"Запам'ятав: «{shown}» більше не виправлятиму")

    def _learn_manual(self, lang, word):
        """Two manual fixes of the same word in the same layout => auto-fix it."""
        if not self.cfg["learn"] or len(word) < 2:
            return
        key = f"{lang}:{word.lower()}"
        n = self.learned["manual"].get(key, 0) + 1
        self.learned["manual"][key] = n
        if n >= 2:
            del self.learned["manual"][key]
            self._learn("switch", lang, word)
        else:
            self._save_learned(self.learned)
