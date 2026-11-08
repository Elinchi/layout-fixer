"""Engine against a fake screen: physical keys and our retyping both land on it."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from evdev import ecodes as e

import config
from engine import Engine
from keyboard import KEY_OF
from layouts import to_uk
from model import Model
from train import ROOT

MODEL = Model.load(os.path.join(ROOT, "data/model.json.gz"))


class Screen:
    def __init__(self, lang="en"):
        self.text, self.lang, self.clip = "", lang, ""

    def put(self, keys):
        self.text += keys if self.lang == "en" else to_uk(keys)


class FakeTypist:
    def __init__(self, scr):
        self.scr = scr

    def backspace(self, n):
        self.scr.text = self.scr.text[:-n] if n else self.scr.text

    def type_keys(self, keys):
        self.scr.put(keys)


class FakeLayout:
    def __init__(self, scr):
        self.scr = scr

    def lang(self, dev):
        return self.scr.lang

    def switch(self, lang):
        self.scr.lang = lang


class FakeClip:
    def __init__(self, scr):
        self.scr = scr

    def primary(self):
        return self.scr.clip

    def paste(self, text, cls):
        self.scr.text += text


def make(lang="en", mode="auto", window="org.telegram.desktop"):
    scr = Screen(lang)
    cfg = {**config.DEFAULTS, "mode": mode, "hotkeys": dict(config.DEFAULTS["hotkeys"])}
    notes = []
    learned = {"keep": [], "switch": [], "manual": {}}
    eng = Engine(MODEL, cfg, learned, FakeTypist(scr), FakeLayout(scr), FakeClip(scr),
                 notes.append, lambda c: None, lambda l: None)
    eng.on_window(window, False)
    return eng, scr, notes


T = [0.0]


def press(eng, scr, code, shift=False):
    T[0] += 0.05
    if shift:
        eng.on_key(e.KEY_LEFTSHIFT, 1, "kbd", T[0])
    eng.on_key(code, 1, "kbd", T[0])
    # what the compositor would show for the physical key
    for ch, (k, sh) in KEY_OF.items():
        if k == code and sh == shift:
            scr.put(ch)
            break
    if code == e.KEY_BACKSPACE:
        scr.text = scr.text[:-1]
    eng.on_key(code, 0, "kbd", T[0])
    if shift:
        eng.on_key(e.KEY_LEFTSHIFT, 0, "kbd", T[0])
    if not eng.held:
        eng.run_pending()


def type_text(eng, scr, keys):
    for ch in keys:
        code, shift = KEY_OF[ch]
        press(eng, scr, code, shift)


def double_tap(eng, mod=e.KEY_LEFTSHIFT):
    for _ in range(2):
        T[0] += 0.1
        eng.on_key(mod, 1, "kbd", T[0])
        eng.on_key(mod, 0, "kbd", T[0] + 0.01)
    eng.run_pending()


def check(name, got, want):
    ok = got == want
    print(f"{'ok  ' if ok else 'FAIL'} {name}: {got!r}" + ("" if ok else f" (want {want!r})"))
    return ok


def main():
    res = []
    eng, scr, _ = make("en")
    type_text(eng, scr, "ghbdsn zr cghfdb? ")
    res.append(check("auto: whole phrase in wrong layout", scr.text, "привіт як справи, "))

    eng, scr, _ = make("en")
    type_text(eng, scr, "ckfdf ")
    res.append(check("auto switched the layout", scr.lang, "uk"))
    type_text(eng, scr, "Erhf]ys ")
    res.append(check("auto: next words typed in uk", scr.text, "слава Україні "))

    eng, scr, _ = make("en")
    type_text(eng, scr, "can you check why ffmpeg fails on Wayland ")
    res.append(check("auto: correct English untouched", scr.text,
                     "can you check why ffmpeg fails on Wayland "))

    eng, scr, _ = make("en")
    type_text(eng, scr, "ghbdsn ")
    double_tap(eng)
    res.append(check("undo of auto fix", scr.text, "ghbdsn "))
    res.append(check("undo learned keep", eng.learned["keep"], ["en:ghbdsn"]))
    type_text(eng, scr, "ghbdsn ")
    res.append(check("learned word not fixed again", scr.text, "ghbdsn ghbdsn "))

    eng, scr, _ = make("en", mode="manual")
    type_text(eng, scr, "ghbdsn ")
    res.append(check("manual mode: no auto", scr.text, "ghbdsn "))
    double_tap(eng)
    res.append(check("manual hotkey fixes last word", scr.text, "привіт "))
    double_tap(eng)
    res.append(check("pressing again toggles back", scr.text, "ghbdsn "))

    eng, scr, _ = make("en", mode="manual")
    type_text(eng, scr, "ghbd")
    double_tap(eng)
    res.append(check("hotkey mid-word", scr.text, "прив"))
    type_text(eng, scr, "sn")
    res.append(check("continue in new layout", scr.text, "привіт"))

    eng, scr, _ = make("en", window="com.mitchellh.ghostty")
    type_text(eng, scr, "ghbdsn ")
    res.append(check("terminal excluded from auto", scr.text, "ghbdsn "))

    eng, scr, _ = make("en")
    type_text(eng, scr, "gthtp,shrf kernel vjlekz")
    res.append(check("mid-word: last word fixed before Enter", scr.text,
                     "перезбірка kernel модуля"))
    double_tap(eng)
    res.append(check("mid-word fix can be undone", scr.text, "перезбірка kernel vjlekz"))

    eng, scr, _ = make("en")
    type_text(eng, scr, '"vjlekm')
    res.append(check("mid-word after an opening quote", scr.text, '"модуль'))

    eng, scr, _ = make("en")
    type_text(eng, scr, '"gthtp,shrf kernel vjlekz" ')
    res.append(check("quotes kept around fixed words", scr.text,
                     '"перезбірка kernel модуля" '))

    eng, scr, _ = make("en")
    type_text(eng, scr, '"ghbdsn" wt ntcn? ')
    res.append(check("closing quote out of en habit", scr.text, '"привіт" це тест, '))

    eng, scr, _ = make("en")
    type_text(eng, scr, '[v ')
    res.append(check("interjection", scr.text, 'хм '))

    eng, scr, _ = make("en")
    eng.on_window("org.omarchy.agent", False, window_id="0x1")
    type_text(eng, scr, "ghbd")
    eng.on_window("org.omarchy.agent", False, window_id="0x1")   # title spinner tick
    type_text(eng, scr, "sn ")
    res.append(check("title change keeps the word", scr.text, "привіт "))
    eng.on_window("org.omarchy.agent", False, window_id="0x2")
    res.append(check("another window resets", eng.buf, []))

    eng, scr, _ = make("en", window="cs2")
    type_text(eng, scr, "ghbdsn ")
    double_tap(eng)
    res.append(check("game: no auto, no hotkeys", scr.text, "ghbdsn "))

    eng, scr, notes = make("uk")
    eng.on_selection(T[0] + 1)
    T[0] += 2
    scr.text, scr.clip = "", "руддщ цщкдв"
    double_tap(eng, e.KEY_LEFTCTRL)
    res.append(check("selection uk->en", scr.text, "hello world"))

    eng, scr, notes = make("en")
    type_text(eng, scr, "abc")
    eng.on_selection(T[0] - 1)            # stale selection from before typing
    double_tap(eng, e.KEY_LEFTCTRL)
    res.append(check("stale selection refused", notes[-1:], ["Спочатку виділіть текст"]))

    eng, scr, _ = make("en")
    type_text(eng, scr, "ghbdsn")
    press(eng, scr, e.KEY_BACKSPACE)
    press(eng, scr, e.KEY_BACKSPACE)
    type_text(eng, scr, "sn ")
    res.append(check("backspace inside word", scr.text, "привіт "))

    eng, scr, _ = make("en", mode="log")
    type_text(eng, scr, "ghbdsn ")
    res.append(check("log mode changes nothing", scr.text, "ghbdsn "))
    res.append(check("log mode records", len(eng.log), 1))

    print(f"\n{sum(res)}/{len(res)} passed")
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
