#!/usr/bin/env python3
"""Copia dictionary builder.

Generates the versioned word-list artifact embedded in copia.html:
  - every 4-12 letter a-z word from words-enable.txt is scored with
    wordfreq's zipf_frequency('en')
  - find list ("words to find") = zipf >= FIND_ZIPF
  - bonus words               = BONUS_ZIPF <= zipf < FIND_ZIPF
  - words are ranked in descending frequency (ties broken alphabetically)
    across both tiers; rank feeds the in-game rarity score
  - NAME-POLLUTION POLICY (see find_names.py for the analysis behind it):
    wordfreq case-folds, so name-heavy strings get inflated zipf. Using
    SUBTLEX-US case counts (FREQcount/FREQlow), find-tier words are:
      * removed entirely   if cap_ratio >= NAME_REMOVE_RATIO (0.95)  (marc, york)
      * demoted to bonus   if cap_ratio >= NAME_DEMOTE_RATIO (0.90)  (united)
      * demoted to bonus   if absent from SUBTLEX (frequency must come from
        case-folded web corpora; also catches post-2007 internet vocabulary,
        which is an accepted trade-off)                              (tian, meme)
      * left alone         if SUBTLEX evidence < NAME_MIN_COUNT (sparse)
    build/name-allowlist.txt (one word per line, # comments) exempts words
    from this policy entirely. Bonus-tier words are not policed.
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

DICT_VERSION = 4
FIND_ZIPF = 3.0
BONUS_ZIPF = 2.0
WORD_RE = re.compile(r"^[a-z]{4,12}$")

NAME_REMOVE_RATIO = 0.95
NAME_DEMOTE_RATIO = 0.90
NAME_MIN_COUNT = 5

HERE = pathlib.Path(__file__).resolve().parent
SOURCE_WORDS = HERE / "words-enable.txt"
SUBTLEX_TSV = HERE / "SUBTLEXus74286wordstextversion.tsv"
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


def load_subtlex_case():
    """word(lower) -> (FREQcount, FREQlow), summed over case variants."""
    stats = {}
    for line in SUBTLEX_TSV.read_text().split("\n")[1:]:
        if not line.strip():
            continue
        p = line.split("\t")
        w = p[0].lower()
        t, l = int(p[1]), int(p[3])
        t0, l0 = stats.get(w, (0, 0))
        stats[w] = (t0 + t, l0 + l)
    return stats


def load_allowlist():
    p = HERE / "name-allowlist.txt"
    if not p.exists():
        return set()
    return {l.strip() for l in p.read_text().split("\n")
            if l.strip() and not l.startswith("#")}


def apply_name_policy(find_words):
    """Split find_words into (keep, demote, remove) per the module docstring."""
    case = load_subtlex_case()
    allow = load_allowlist()
    keep, demote, remove = [], [], []
    for w in find_words:
        if w in allow:
            keep.append(w)
            continue
        st = case.get(w)
        if st is None:                       # NO-EVIDENCE -> demote
            demote.append(w)
            continue
        total, low = st
        if total < NAME_MIN_COUNT:           # SPARSE -> leave alone
            keep.append(w)
            continue
        ratio = 1 - low / total
        if ratio >= NAME_REMOVE_RATIO:
            remove.append(w)
        elif ratio >= NAME_DEMOTE_RATIO:
            demote.append(w)
        else:
            keep.append(w)
    return keep, demote, remove


def build():
    words = [w for w in SOURCE_WORDS.read_text().split("\n") if WORD_RE.match(w)]
    scored = sorted(((zipf(w), w) for w in words), key=lambda t: (-t[0], t[1]))
    find_words = [w for z, w in scored if z >= FIND_ZIPF]
    bonus_words = [w for z, w in scored if BONUS_ZIPF <= z < FIND_ZIPF]
    find_words, demoted, removed = apply_name_policy(find_words)
    # demoted words all have zipf >= FIND_ZIPF > every bonus word, so
    # prepending keeps the bonus section in descending-frequency order
    bonus_words = demoted + bonus_words

    # ---- stem-family promotion ----
    # If a find-list word is a suffix extension of a word sitting in the bonus
    # tier — whether naturally rarer (oriented 4.1 vs orient 3.4-demoted) or
    # pushed there by the name policy — players who see the base as a mere
    # bonus word stop hunting its extensions. Promote the base into the find
    # list; the extension then scores x0 whenever the base is on the same
    # board (and the UI drops it), by the existing stem mechanics. Iterated to
    # a fixpoint so promotion chains resolve. Promoted words are appended
    # after the natural find words in their own descending-frequency order,
    # so the find section stays two sorted runs (documented format quirk).
    bonus_set = set(bonus_words)
    promoted = []
    frontier = list(find_words)
    while frontier:
        nxt = []
        for w in frontier:
            for b in pattern_bases(w, bonus_set):
                bonus_set.discard(b)
                promoted.append(b)
                nxt.append(b)
        frontier = nxt
    if promoted:
        promoted.sort(key=lambda w: (-zipf(w), w))
        find_words = find_words + promoted
        bonus_words = [w for w in bonus_words if w in bonus_set]

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
    print(f"name policy: removed={len(removed)} demoted-to-bonus={len(demoted)}; "
          f"stem promotion: {len(promoted)} bases promoted to find list")
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
