# Copia dictionary build

The game's word list is a generated, versioned artifact — it is NOT built at
deploy time. `dict/copia-dict.v<N>.txt` is checked into the repo and embedded
into `copia.html` by this build script.

## Rebuilding

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python build_dict.py --inject

## Rules

- Bump `DICT_VERSION` in `build_dict.py` for any change that alters the
  output (thresholds, source list, lemmatization, format).
- Keep old `dict/copia-dict.v*.txt` files; each version is a permanent record
  of what boards of that era were generated from.
- Bump `GEN_VERSION` in `copia.html` in the same commit — dictionary changes
  reshuffle all board names.

## Sources

- `words-enable.txt`: the ENABLE word list as shipped in the `word-list` npm
  package v4.1.0 (ENABLE with offensive words removed).
- Frequency: `wordfreq` (zipf_frequency, English).
- Lemmatization: `lemminflect` (see build_dict.py docstring for the stem
  policy and false-positive gating).
