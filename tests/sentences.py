"""Simulate typing whole sentences: each word in the right layout (nothing may
change) and each word in the wrong layout (every word should be fixed)."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from layouts import to_keys, to_uk
from model import Model, decide, lang_of, norm_apostrophe
from train import ROOT

SENTENCES = [
    "скачай мені Minecraft мод, написаний на Rust, щоб він запускався на Forge",
    "шо там по RTX Remix, вже запускається на Linux чи ще капєц?",
    "глянь логи Hyprland, тіпа там якась хуйня з NVIDIA драйвером",
    "привіт, як справи? я сьогодні ваще нічого не встиг",
    "can you check why ffmpeg fails on Wayland",
    "короче, кинь мені посилання на GitHub, я перевірю",
]


def words(sentence):
    for w in sentence.split():
        core = norm_apostrophe(w.strip(",.?!:;")).lower()
        yield w, lang_of(core) or "en"


def show(sentence, wrong, model):
    out, changed = [], 0
    for w, lang in words(sentence):
        keys = w if lang == "en" else to_keys(w)
        typed_in = ("uk" if lang == "en" else "en") if wrong else lang
        on_screen = keys if typed_in == "en" else to_uk(keys)
        dsn = decide(keys, typed_in, model)
        if dsn.switch:
            changed += 1
            fixed = keys if typed_in == "uk" else to_uk(keys)
            out.append(f"[{on_screen}→{fixed}]")
        else:
            out.append(on_screen)
    return changed, " ".join(out)


def main():
    model = Model.load(os.path.join(ROOT, "data/model.json.gz"))
    for s in SENTENCES:
        n = len(s.split())
        c, text = show(s, False, model)
        print(f"right layout, changed {c}/{n}: {text}")
        c, text = show(s, True, model)
        print(f"wrong layout, fixed   {c}/{n}: {text}\n")
    t = time.perf_counter()
    for _ in range(20000):
        decide("ghbdsn", "en", model)
    print(f"decide(): {(time.perf_counter() - t) / 20000 * 1e6:.1f} µs per word")


if __name__ == "__main__":
    main()
