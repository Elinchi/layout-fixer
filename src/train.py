"""Build model.json.gz from the Leipzig corpora (+ optional personal texts).

usage: python src/train.py [--extra FILE[:WEIGHT] ...]
FILE may be plain text or a Telegram Desktop export (result.json).
The last HOLDOUT share of every corpus file is left out for tests/eval.py.
"""

import argparse
import glob
import gzip
import io
import json
import os
import re
import subprocess
import tarfile
import urllib.request

from model import Model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDOUT = 0.1
CORPORA_URL = "https://downloads.wortschatz-leipzig.de/corpora/{}.tar.gz"
CORPORA = ["ukr_news_2020_100K", "ukr_wikipedia_2021_100K", "ukr-ua_web_2015_100K",
           "eng_news_2020_100K", "eng-com_web-public_2018_100K"]


def download_corpora():
    """Fetch the Leipzig sentence files (~80 MB unpacked); only *-sentences.txt is kept."""
    for name in CORPORA:
        dest = os.path.join(ROOT, "data/raw", name)
        if glob.glob(os.path.join(dest, "*/*-sentences.txt")):
            continue
        print(f"downloading {name} ...")
        with urllib.request.urlopen(CORPORA_URL.format(name), timeout=120) as r:
            blob = r.read()
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            members = [m for m in tar.getmembers()
                       if m.isfile() and m.name.endswith("-sentences.txt")]
            tar.extractall(dest, members=members, filter="data")


def corpus_files():
    return sorted(glob.glob(os.path.join(ROOT, "data/raw/*/*/*-sentences.txt")))


def corpus_lines(path, part):
    with open(path, encoding="utf-8") as f:
        lines = [l.split("\t", 1)[-1] for l in f]
    cut = int(len(lines) * (1 - HOLDOUT))
    return lines[:cut] if part == "train" else lines[cut:]


def telegram_texts(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    chats = data.get("chats", {}).get("list", [data])
    # Full exports name the owner; keep only their messages (how *you* type).
    me = data.get("personal_information", {}).get("user_id")
    for chat in chats:
        for msg in chat.get("messages", []):
            if me and msg.get("from_id") != f"user{me}":
                continue
            t = msg.get("text", "")
            if isinstance(t, list):
                t = "".join(p if isinstance(p, str) else p.get("text", "") for p in t)
            if t:
                yield t


def extra_texts(spec):
    path, _, w = spec.partition(":")
    weight = int(w or 1)
    if path.endswith(".json"):
        for t in telegram_texts(path):
            yield weight, t
    else:
        with open(path, encoding="utf-8") as f:
            for line in f:
                yield weight, line


def lexicon_texts():
    """data/lexicon/<lang>.txt: hand-kept words, weighted to count as frequent."""
    from model import STRONG_WORD
    for path in sorted(glob.glob(os.path.join(ROOT, "data/lexicon/*.txt"))):
        with open(path, encoding="utf-8") as f:
            for line in f:
                yield STRONG_WORD * 5, line.split("#", 1)[0]


def tech_words():
    """Package and command names on this machine: wtype, ffmpeg, dxvk, ..."""
    cmd = "pacman -Slq; pacman -Qq; compgen -c"
    out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True).stdout
    words = set()
    for name in out.split():
        for part in re.split(r"[-_.+]", name.lower()):
            if len(part) >= 3 and re.fullmatch(r"[a-z]+", part):
                words.add(part)
    return sorted(words)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--out", default=os.path.join(ROOT, "data/model.json.gz"))
    args = ap.parse_args()

    download_corpora()

    def texts():
        for p in corpus_files():
            for line in corpus_lines(p, "train"):
                yield 1, line
        for spec in args.extra:
            yield from extra_texts(spec)
        yield from lexicon_texts()

    data = Model.train(texts())
    data["tech"] = tech_words()
    with gzip.open(args.out, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    for l in ("en", "uk"):
        print(f"{l}: {data[l]['total']} tokens, {len(data[l]['words'])} known words, "
              f"{len(data[l]['tri'])} trigrams")
    print(f"tech words: {len(data['tech'])}")
    print(f"-> {args.out} ({os.path.getsize(args.out) // 1024} KiB)")


if __name__ == "__main__":
    main()
