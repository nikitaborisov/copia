#!/usr/bin/env python3
"""Find name-polluted words in the find tier (analysis only — changes nothing).

Problem: wordfreq case-folds its corpora, so dictionary-legal strings whose
real-world frequency comes from proper nouns (marc, lear, ares, cate) sneak
into the find tier with inflated zipf scores.

Signal: SUBTLEX-US full text version (build/SUBTLEXus74286wordstextversion.tsv,
from crr.ugent.be) provides per-word FREQcount (total occurrences) and FREQlow
(occurrences in lowercase). cap_ratio = 1 - FREQlow/FREQcount is an honest
capitalization rate: sentence-initial words like "come" still show plenty of
lowercase use (low ratio), while true names are capitalized nearly always.

Buckets for find-tier words:
  NAME-DOMINANT  cap_ratio >= --ratio (default 0.9), FREQcount >= --min-count
                 -> demote these
  MIXED          0.5 <= cap_ratio < --ratio -> borderline, manual review
  NO-EVIDENCE    absent from SUBTLEX despite zipf >= 3 -> frequency comes from
                 case-folded web corpora (tian); gazetteer hit noted as extra
                 evidence; review, mostly demotable
  (everything else is clean)

Words in build/name-allowlist.txt (one per line, # comments) are never
flagged — for words where the name genuinely dominates usage but the common
word is one players know (e.g. bill, mark).

Usage:
  python3 find_names.py [--ratio 0.9] [--min-count 5] [--top 40]

Writes the full report to build/name-candidates.txt (untracked), sorted by
zipf desc (most game-visible first).
"""
import argparse
import pathlib
import re

from wordfreq import zipf_frequency

HERE = pathlib.Path(__file__).resolve().parent
SUBTLEX_TSV = HERE / "SUBTLEXus74286wordstextversion.tsv"
DICT_GLOB = "copia-dict.v*.txt"

MONTHS = {"january", "february", "march", "april", "june", "july", "august",
          "september", "october", "november", "december"}
WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday"}
NATIONALITIES = {"english", "french", "german", "spanish", "italian",
                 "russian", "chinese", "japanese", "korean", "indian",
                 "american", "british", "irish", "scottish", "welsh",
                 "dutch", "greek", "polish", "swedish", "turkish", "arabic",
                 "mexican", "canadian", "brazilian", "african", "european",
                 "asian", "australian", "egyptian", "persian", "roman"}


def latest_dict():
    arts = sorted((HERE.parent / "dict").glob(DICT_GLOB),
                  key=lambda p: int(re.search(r"v(\d+)", p.name).group(1)))
    return arts[-1]


def load_find_words(path):
    words, in_find = [], False
    for line in path.read_text().split("\n")[1:]:
        if line == "#find":
            in_find = True
        elif line == "#bonus":
            break
        elif in_find and line:
            words.append(line.split(":")[0])
    return words


def load_subtlex_case():
    """word(lower) -> (FREQcount, FREQlow), summed over case variants."""
    stats = {}
    lines = SUBTLEX_TSV.read_text().split("\n")
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        w = parts[0].lower()
        total, low = int(parts[1]), int(parts[3])
        t0, l0 = stats.get(w, (0, 0))
        stats[w] = (t0 + total, l0 + low)
    return stats


def load_allowlist():
    p = HERE / "name-allowlist.txt"
    if not p.exists():
        return set()
    return {l.strip() for l in p.read_text().split("\n")
            if l.strip() and not l.startswith("#")}


def load_gazetteer():
    """Optional extra evidence for NO-EVIDENCE words. Skipped if packages
    are missing. Census surnames excluded (too many real English words)."""
    try:
        import names as names_pkg
        import geonamescache
    except ImportError:
        return set()
    gaz = set(MONTHS) | set(WEEKDAYS) | set(NATIONALITIES)
    d = pathlib.Path(names_pkg.__file__).parent
    for f in ["dist.male.first", "dist.female.first"]:
        for line in (d / f).read_text().split("\n"):
            if line.strip():
                gaz.add(line.split()[0].lower())
    gc = geonamescache.GeonamesCache()
    for c in gc.get_cities().values():
        gaz.add(c["name"].lower())
    for c in gc.get_countries().values():
        gaz.add(c["name"].lower())
    for s in gc.get_us_states().values():
        gaz.add(s["name"].lower())
    return gaz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", type=float, default=0.9,
                    help="cap_ratio threshold for NAME-DOMINANT")
    ap.add_argument("--min-count", type=int, default=5,
                    help="min SUBTLEX FREQcount for a ratio to be trusted")
    ap.add_argument("--top", type=int, default=40, help="rows to print per bucket")
    args = ap.parse_args()

    art = latest_dict()
    find_words = load_find_words(art)
    case = load_subtlex_case()
    allow = load_allowlist()
    gaz = load_gazetteer()

    flagged = []  # (zipf, word, category, evidence)
    n_clean = 0
    for w in find_words:
        if w in allow:
            n_clean += 1
            continue
        st = case.get(w)
        if st is None:
            note = ", gazetteer" if w in gaz else ""
            flagged.append((zipf_frequency(w, "en"), w, "NO-EVIDENCE",
                            f"absent from SUBTLEX{note}"))
            continue
        total, low = st
        if total < args.min_count:
            # a find-tier word (zipf>=3) that subtitles barely know is itself
            # suspicious — its wordfreq frequency came from elsewhere
            note = ", gazetteer" if w in gaz else ""
            flagged.append((zipf_frequency(w, "en"), w, "SPARSE",
                            f"SUBTLEX only {total}x, cap {100*(1-low/total):.0f}%{note}"))
            continue
        ratio = 1 - low / total
        ev = f"cap {100*ratio:.0f}% ({total-low}/{total})"
        if ratio >= args.ratio:
            flagged.append((zipf_frequency(w, "en"), w, "NAME-DOMINANT", ev))
        elif ratio >= 0.5:
            flagged.append((zipf_frequency(w, "en"), w, "MIXED", ev))
        else:
            n_clean += 1
    flagged.sort(reverse=True)

    by_cat = {}
    for z, w, cat, ev in flagged:
        by_cat[cat] = by_cat.get(cat, 0) + 1
    print(f"dict artifact: {art.name}   find tier: {len(find_words)} words")
    print(f"clean/allowlisted: {n_clean}   flagged: {len(flagged)}  {by_cat}")
    for want in ["NAME-DOMINANT", "MIXED", "NO-EVIDENCE", "SPARSE"]:
        rows = [f for f in flagged if f[2] == want]
        print(f"\n== {want} ({len(rows)}) — top {min(args.top, len(rows))} by zipf ==")
        for z, w, cat, ev in rows[:args.top]:
            print(f"  {w:14} {z:5.2f}  {ev}")

    out = HERE / "name-candidates.txt"
    out.write_text("\n".join(f"{w}\t{z:.2f}\t{cat}\t{ev}"
                             for z, w, cat, ev in flagged))
    print(f"\nfull report -> {out} ({len(flagged)} words)")


if __name__ == "__main__":
    main()
