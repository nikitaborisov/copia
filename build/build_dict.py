#!/usr/bin/env python3
"""Copia dictionary builder.

Generates the versioned word-list artifact embedded in copia.html:
  - every 4-12 letter a-z word from words-enable.txt is scored with
    wordfreq's zipf_frequency('en')
  - find list ("words to find") = zipf >= FIND_ZIPF
  - bonus words               = BONUS_ZIPF <= zipf < FIND_ZIPF
  - words are ranked in descending frequency (ties broken alphabetically)
    across both tiers; rank feeds the in-game rarity score
  - each word is annotated with its stem bases (for the stem penalty),
    computed by simple suffix patterns only — NOT full lemmatization:
      * foo -> foos        (add s)
      * foo -> fooed       (add ed)
      * bare -> bared      (replace trailing e with d)
      * bar -> barred      (double last letter + ed)
      * bar -> baring      (add ing)
      * bar -> barring     (double last letter + ing)
      * bare -> baring     (replace trailing e with ing)
    Other inflections (bury->buries, mice->mouse, etc.) are not stemmed.
    Only bases that are themselves in the find list are stored, since the
    in-game penalty only applies when the stem is on the same board.

Output format (docs/parsing must stay in sync with engine.js):
  line 1: "copia-dict v<DICT_VERSION>"
  "#find" line, then find words in rank order
  "#bonus" line, then bonus words in rank order
  each word line: "word" or "word:base1,base2" (bases alphabetically)

VERSIONING: bump DICT_VERSION for ANY change to this script's output
(thresholds, source list, stemming logic, format). Check the new
artifact in as dict/copia-dict.v<N>.txt (keep old versions), inject it with
--inject, and bump GEN_VERSION in engine.js in the same commit — board
names reshuffle whenever the dictionary changes.

Usage:
  python3 build_dict.py                 # writes ../dict/copia-dict.v<N>.txt
  python3 build_dict.py --inject        # ...and splices it into ../copia.html

Requires: pip install -r requirements.txt
"""
import argparse
import pathlib
import re
import sys

from wordfreq import zipf_frequency

DICT_VERSION = 2
FIND_ZIPF = 3.0
BONUS_ZIPF = 2.0
WORD_RE = re.compile(r"^[a-z]{4,12}$")

HERE = pathlib.Path(__file__).resolve().parent
SOURCE_WORDS = HERE / "words-enable.txt"
OUT_DIR = HERE.parent / "dict"
GAME_HTML = HERE.parent / "copia.html"


def zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def pattern_bases(word: str, find_set: set) -> set:
    """Simple suffix-pattern bases only (see module docstring)."""
    bases = set()
    n = len(word)

    # foo -> foos (add s)
    if word.endswith("s") and n > 4:
        b = word[:-1]
        if b in find_set:
            bases.add(b)

    # foo -> fooed (add ed)
    if word.endswith("ed") and n > 5:
        b = word[:-2]
        if b in find_set and word == b + "ed":
            bases.add(b)

    # bare -> bared (add d when base ends in e)
    if word.endswith("d") and n >= 5:
        b = word[:-1]
        if b in find_set and b.endswith("e") and word == b + "d":
            bases.add(b)

    # bar -> barred (double last letter + ed)
    if word.endswith("ed") and n >= 7:
        b = word[:-3]
        if len(b) >= 4 and b in find_set and word == b + b[-1] + "ed":
            bases.add(b)

    # bar -> baring (add ing)
    if word.endswith("ing") and n >= 7:
        b = word[:-3]
        if b in find_set and word == b + "ing":
            bases.add(b)

    # bar -> barring (double last letter + ing)
    if word.endswith("ing") and n >= 8:
        b = word[:-4]
        if len(b) >= 4 and b in find_set and word == b + b[-1] + "ing":
            bases.add(b)

    # bare -> baring (replace trailing e with ing)
    if word.endswith("ing") and n >= 6:
        b = word[:-3] + "e"
        if b in find_set and word == b[:-1] + "ing":
            bases.add(b)

    return bases


def build():
    words = [w for w in SOURCE_WORDS.read_text().split("\n") if WORD_RE.match(w)]
    scored = sorted(((zipf(w), w) for w in words), key=lambda t: (-t[0], t[1]))
    find_words = [w for z, w in scored if z >= FIND_ZIPF]
    bonus_words = [w for z, w in scored if BONUS_ZIPF <= z < FIND_ZIPF]
    find_set = set(find_words)

    def annotate(word: str) -> str:
        bases = pattern_bases(word, find_set)
        if not bases:
            return word
        return word + ":" + ",".join(sorted(bases))

    lines = [f"copia-dict v{DICT_VERSION}", "#find"]
    lines += [annotate(w) for w in find_words]
    lines.append("#bonus")
    lines += [annotate(w) for w in bonus_words]
    text = "\n".join(lines)
    if "</script>" in text:
        sys.exit("unsafe content in dictionary")

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"copia-dict.v{DICT_VERSION}.txt"
    out.write_text(text)
    stems = sum(1 for l in lines if ":" in l)
    print(f"wrote {out}  find={len(find_words)} bonus={len(bonus_words)} "
          f"stem-annotated={stems}")
    return text


def inject(text: str):
    html = GAME_HTML.read_text()
    pattern = re.compile(
        r'<script id="dict-data" type="text/plain">.*?</script>', re.S)
    replacement = f'<script id="dict-data" type="text/plain">{text}</script>'
    if not pattern.search(html):
        sys.exit("dict-data block not found in copia.html")
    GAME_HTML.write_text(pattern.sub(lambda _: replacement, html))
    print(f"injected into {GAME_HTML}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--inject", action="store_true",
                    help="splice the generated dictionary into copia.html")
    args = ap.parse_args()
    text = build()
    if args.inject:
        inject(text)
