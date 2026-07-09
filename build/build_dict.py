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
    computed by real lemmatization (lemminflect), NOT suffix heuristics:
      * inflectional forms (rains->rain, buries->bury, mice->mouse) come
        straight from lemminflect
      * derivational -er/-r(+s) agent nouns (singer->sing) and words unknown
        to lemminflect (motes->mote) go through suffix rules gated by a
        frequency sanity check: the base must be MORE frequent than the
        derived form. This is what blocks false positives like brand->bran,
        corner->corn, beard->bear.
    Only bases that are themselves in the find list are stored, since the
    in-game penalty only applies when the stem is on the same board.

Output format (docs/parsing must stay in sync with engine.js):
  line 1: "copia-dict v<DICT_VERSION>"
  "#find" line, then find words in rank order
  "#bonus" line, then bonus words in rank order
  each word line: "word" or "word:base1,base2" (bases sorted: prefix bases
  first — the game maps prefix bases to the 1/8 penalty, others to 1/4)

VERSIONING: bump DICT_VERSION for ANY change to this script's output
(thresholds, source list, lemmatization logic, format). Check the new
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

from lemminflect import getAllLemmas
from wordfreq import zipf_frequency

DICT_VERSION = 1
FIND_ZIPF = 3.0
BONUS_ZIPF = 2.0
WORD_RE = re.compile(r"^[a-z]{4,12}$")

HERE = pathlib.Path(__file__).resolve().parent
SOURCE_WORDS = HERE / "words-enable.txt"
OUT_DIR = HERE.parent / "dict"
GAME_HTML = HERE.parent / "copia.html"

AGENT_SUFFIXES = ["ers", "rs", "er", "r"]


def zipf(word: str) -> float:
    return zipf_frequency(word, "en")


def lemma_bases(word: str, find_set: set) -> set:
    """True inflectional bases from lemminflect (rains->rain, mice->mouse)."""
    bases = set()
    for lemmas in getAllLemmas(word).values():
        for lemma in lemmas:
            if lemma != word and lemma in find_set:
                bases.add(lemma)
    return bases


def agent_noun_bases(word: str, find_set: set, z_word: float) -> set:
    """Derivational -er/-r agent nouns: singer->sing, mover->move.
    Gated: base must be a known VERB lemma and more frequent than the word."""
    bases = set()
    for suf in AGENT_SUFFIXES:
        if not word.endswith(suf) or len(word) - len(suf) < 4:
            continue
        base = word[: len(word) - len(suf)]
        for cand in {base, base + "e"}:
            if cand in find_set and cand != word and zipf(cand) > z_word:
                if "VERB" in getAllLemmas(cand):
                    bases.add(cand)
    return bases


def fallback_bases(word: str, find_set: set, z_word: float) -> set:
    """Suffix heuristics for words lemminflect does not know (motes->mote),
    frequency-gated so brand->bran style accidents stay out."""
    cands = set()
    n = len(word)
    for suf in ["s", "es", "ed", "d", "ing", "er", "r", "ers", "rs", "est", "st"]:
        if word.endswith(suf) and n - len(suf) >= 4:
            cands.add(word[: n - len(suf)])
    for suf, rep in [("ies", "y"), ("ied", "y"), ("ier", "y"), ("iest", "y")]:
        if word.endswith(suf) and n - len(suf) >= 3:
            cands.add(word[: n - len(suf)] + rep)
    if word.endswith("ing") and n >= 6:
        cands.add(word[:-3] + "e")
    for suf in ["ed", "ing", "er", "est"]:
        if word.endswith(suf):
            b = word[: n - len(suf)]
            if len(b) >= 5 and b[-1] == b[-2]:
                cands.add(b[:-1])
    return {b for b in cands if b != word and b in find_set and zipf(b) > z_word}


def build():
    words = [w for w in SOURCE_WORDS.read_text().split("\n") if WORD_RE.match(w)]
    scored = sorted(((zipf(w), w) for w in words), key=lambda t: (-t[0], t[1]))
    find_words = [w for z, w in scored if z >= FIND_ZIPF]
    bonus_words = [w for z, w in scored if BONUS_ZIPF <= z < FIND_ZIPF]
    find_set = set(find_words)

    def annotate(word: str) -> str:
        z_word = zipf(word)
        bases = lemma_bases(word, find_set)
        bases |= agent_noun_bases(word, find_set, z_word)
        if not getAllLemmas(word):
            bases |= fallback_bases(word, find_set, z_word)
        if not bases:
            return word
        ordered = sorted(bases, key=lambda b: (not word.startswith(b), b))
        return word + ":" + ",".join(ordered)

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
