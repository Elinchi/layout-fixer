"""Character-trigram language models for en/uk and the switch decision.

Lookups are dict hits: scoring a word costs O(len(word)), no word-list scans.
"""

import gzip
import json
import math
import re
from collections import Counter
from dataclasses import dataclass

from layouts import EN_LETTERS, UK_LETTERS, norm_apostrophe, to_uk

LANGS = ("en", "uk")
LETTERS = {"en": EN_LETTERS, "uk": UK_LETTERS}
WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʼ‘][^\W\d_]+)*")

# Decision thresholds (tuned with tests/eval.py).
ALPHA = 0.5          # add-alpha smoothing
RARE = 3             # trigram seen fewer times than this => "rare"
MIN_WORD = 3         # corpus count for a word to be "known" (protects it)
STRONG_WORD = 20     # corpus count for a word to count as evidence for switching
MARGIN = 1.0         # alt must beat current by this many nats/char ...
MARGIN_CLEAN = 2.0   # ... or this much when current has no rare trigrams
MARGIN_KNOWN = -1.0  # ... or by this much (may be worse!) when alt is a frequent known word
SHORT_RATIO = 10.0   # words <= 3 letters: alt freq / cur freq needed


def lang_of(token: str) -> str | None:
    chars = set(token) - {"'"}
    if chars <= EN_LETTERS:
        return "en"
    if chars <= UK_LETTERS:
        return "uk"
    return None


def tokens(text: str):
    """Yield (lang, word) for every single-script word in text."""
    for m in WORD_RE.finditer(norm_apostrophe(text).lower()):
        w = m.group()
        lang = lang_of(w)
        if lang:
            yield lang, w


def trigrams(word: str):
    p = "^^" + word + "$"
    for i in range(2, len(p)):
        yield p[i - 2:i], p[i]


class Model:
    def __init__(self, data: dict):
        self.tri = {l: data[l]["tri"] for l in LANGS}
        self.ctx = {l: data[l]["ctx"] for l in LANGS}
        self.words = {l: data[l]["words"] for l in LANGS}
        self.total = {l: max(1, data[l]["total"]) for l in LANGS}
        self.vocab = {l: len(LETTERS[l]) + 2 for l in LANGS}
        self.tech = set(data.get("tech", []))
        self.user = {"keep": set(data.get("keep", [])), "switch": set(data.get("switch", []))}

    # ---- training -------------------------------------------------------
    @staticmethod
    def train(texts_by_weight) -> dict:
        """texts_by_weight: iterable of (weight, text)."""
        words = {l: Counter() for l in LANGS}
        for weight, text in texts_by_weight:
            for lang, w in tokens(text):
                words[lang][w] += weight
        data = {}
        for l in LANGS:
            tri, ctx = Counter(), Counter()
            for w, n in words[l].items():
                for c2, c in trigrams(w):
                    tri[c2 + c] += n
                    ctx[c2] += n
            data[l] = {
                "tri": dict(tri),
                "ctx": dict(ctx),
                "words": {w: n for w, n in words[l].items() if n >= MIN_WORD},
                "total": sum(words[l].values()),
            }
        return data

    @classmethod
    def load(cls, path: str) -> "Model":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f))

    # ---- scoring --------------------------------------------------------
    def score(self, word: str, lang: str):
        """-> (avg log-prob per char, number of rare trigrams)."""
        tri, ctx, v = self.tri[lang], self.ctx[lang], self.vocab[lang]
        logp, rare, n = 0.0, 0, 0
        for c2, c in trigrams(word):
            k = tri.get(c2 + c, 0)
            if k < RARE:
                rare += 1
            logp += math.log((k + ALPHA) / (ctx.get(c2, 0) + ALPHA * v))
            n += 1
        return logp / n, rare

    def freq(self, word: str, lang: str) -> float:
        return self.words[lang].get(word, 0) / self.total[lang]


@dataclass
class Reading:
    lang: str
    text: str        # what this layout produces, original case
    core: str        # lowercased word part, or "" if the reading is impossible
    avg: float = -99.0
    rare: int = 99
    known: bool = False
    strong: bool = False


def word_span(keys: str, lang: str) -> tuple[int, int]:
    """Span of `keys` that forms the word in layout `lang` (punctuation trimmed)."""
    text = norm_apostrophe(keys if lang == "en" else to_uk(keys)).lower()
    is_letter = [c in LETTERS[lang] for c in text]
    if not any(is_letter):
        return 0, 0
    return is_letter.index(True), len(text) - is_letter[::-1].index(True)


def read(keys: str, lang: str, model: Model) -> Reading:
    """Read the whole key run as a word in `lang`; "" core if it can't be one."""
    text = keys if lang == "en" else to_uk(keys)
    core = norm_apostrophe(text).lower()
    letters = LETTERS[lang]
    # Only letters and single inner apostrophes form a word.
    if not re.fullmatch(r"[^']+(?:'[^']+)*", core) or set(core) - letters - {"'"}:
        return Reading(lang, text, "")
    r = Reading(lang, text, core)
    r.avg, r.rare = model.score(core, lang)
    n = model.words[lang].get(core, 0)
    r.known, r.strong = n > 0, n >= STRONG_WORD
    return r


@dataclass
class Decision:
    switch: bool
    reason: str
    cur: Reading
    alt: Reading


def decide(keys: str, cur_lang: str, model: Model) -> Decision:
    """Should the word typed as `keys` in layout `cur_lang` be retyped in the other one?

    Word boundaries come from the current layout (what is on screen), so a
    leading ";" that is "ж" in uk never gets trimmed off to find an en word.
    If that word stays, the untrimmed run gets one more, stricter look: "[eqjdj"
    is "хуйово", and "'" alone is "є". Then a last letter that is punctuation in
    the other layout is dropped: "Кгіеб" is "Rust,".
    On a switch the whole run is retyped in the other layout.
    """
    a, b = word_span(keys, cur_lang)
    res = _decide(keys[a:b], cur_lang, model)
    if res.switch or res.reason in ("user keep", "has digits"):
        return res
    if (a, b) != (0, len(keys)):
        alt = read(keys, res.alt.lang, model)
        if alt.strong or (alt.rare == 0 and res.cur.core and alt.avg - res.cur.avg > MARGIN):
            return Decision(True, "untrimmed run", res.cur, alt)
    if b - a > 2 and not word_span(keys[b - 1], res.alt.lang)[1]:
        sub = _decide(keys[a:b - 1], cur_lang, model)
        if sub.switch:
            return Decision(True, "trailing punctuation: " + sub.reason, sub.cur, sub.alt)
    return res


def _decide(keys: str, cur_lang: str, model: Model) -> Decision:
    alt_lang = "uk" if cur_lang == "en" else "en"
    cur, alt = read(keys, cur_lang, model), read(keys, alt_lang, model)

    def d(sw, why):
        return Decision(sw, why, cur, alt)

    if not keys:
        return d(False, "no word")
    if any(c.isdigit() for c in keys):
        return d(False, "has digits")
    # Learned from the hotkey, per layout: "en:ghbdsn" = switch it when typed in en.
    if f"{cur_lang}:{keys.lower()}" in model.user["keep"]:
        return d(False, "user keep")
    if f"{cur_lang}:{keys.lower()}" in model.user["switch"]:
        return d(True, "user switch")
    if not alt.core:
        return d(False, "alt impossible")
    if not cur.core:
        return d(alt.known or alt.rare == 0, "cur impossible")
    # Package/command names: protect them in en, and accept them as the en
    # reading only when the uk text is not a word and looks wrong.
    if cur_lang == "en" and cur.core in model.tech and not alt.strong:
        return d(False, "tech word")
    if alt_lang == "en" and alt.core in model.tech and not cur.known and cur.rare > 0:
        return d(True, "tech word")
    gain = alt.avg - cur.avg
    if len(keys) <= 3 or (keys.isupper() and len(keys) > 1):
        # Short words and ACRONYMS carry too little letter statistics: only a
        # frequent real word on the other side is enough.
        fc, fa = model.freq(cur.core, cur_lang), model.freq(alt.core, alt_lang)
        return d(alt.strong and fa > SHORT_RATIO * fc, f"short {fa:.1e} vs {fc:.1e}")
    if cur.known:
        return d(False, "cur known")
    if alt.strong and gain > MARGIN_KNOWN:
        return d(True, f"alt known +{gain:.2f}")
    if alt.rare <= cur.rare and gain > (MARGIN if cur.rare else MARGIN_CLEAN):
        return d(True, f"alt better +{gain:.2f}")
    return d(False, f"unsure {gain:+.2f}")
