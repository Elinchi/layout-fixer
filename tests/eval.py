"""Measure the switch decision on held-out corpus words and hand-written cases.

  false switch = word typed in the RIGHT layout got switched (the bad error)
  missed       = word typed in the WRONG layout was left alone
"""

import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from layouts import to_keys
from model import Model, decide, tokens
from train import ROOT, corpus_files, corpus_lines

OTHER = {"en": "uk", "uk": "en"}
SAMPLE = 20000


def keys_of(word, lang):
    return word if lang == "en" else to_keys(word)


def run(words, model, label, show=8):
    """words: list of (lang, word). Prints false-switch and missed rates."""
    fs, ms, fs_ex, ms_ex = 0, 0, Counter(), Counter()
    for lang, w in words:
        k = keys_of(w, lang)
        if decide(k, lang, model).switch:
            fs += 1
            fs_ex[w] += 1
        if not decide(k, OTHER[lang], model).switch:
            ms += 1
            ms_ex[w] += 1
    n = max(1, len(words))
    print(f"{label:28} n={len(words):6}  false switch {100*fs/n:5.2f}%   missed {100*ms/n:5.2f}%")
    if show:
        if fs_ex:
            print("   false:", ", ".join(w for w, _ in fs_ex.most_common(show)))
        if ms_ex:
            print("   missed:", ", ".join(w for w, _ in ms_ex.most_common(show)))


def main():
    model = Model.load(os.path.join(ROOT, "data/model.json.gz"))
    random.seed(1)
    held = {"en": [], "uk": []}
    for p in corpus_files():
        for line in corpus_lines(p, "test"):
            for lang, w in tokens(line):
                held[lang].append(w)
    for lang in ("uk", "en"):
        sample = random.sample(held[lang], min(SAMPLE, len(held[lang])))
        run([(lang, w) for w in sample], model, f"{lang} held-out (by usage)")
        unseen = [w for w in set(held[lang]) if w not in model.words[lang]]
        sample = random.sample(unseen, min(SAMPLE, len(unseen)))
        run([(lang, w) for w in sample], model, f"{lang} unseen words")

    cases = []
    with open(os.path.join(ROOT, "tests/cases.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                lang, *ws = line.split()
                cases += [(lang, w) for w in ws]
    for lang in ("uk", "en"):
        run([c for c in cases if c[0] == lang], model, f"{lang} hand cases", show=40)


if __name__ == "__main__":
    main()
