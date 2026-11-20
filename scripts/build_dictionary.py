#!/usr/bin/env python3
"""Build src/spell/data/en_words.tsv from SCOWL word lists + wordfreq frequencies.

This is a maintainer tool; end users never run it. It needs the SCOWL release
tarball extracted somewhere and the ``wordfreq`` package installed:

    pip install wordfreq
    curl -LO https://downloads.sourceforge.net/project/wordlist/SCOWL/2020.12.07/scowl-2020.12.07.tar.gz
    tar xzf scowl-2020.12.07.tar.gz
    python scripts/build_dictionary.py scowl-2020.12.07

Output format: one entry per line, ``word<TAB>zipf``, where zipf is the
wordfreq Zipf frequency (log10 occurrences per billion words) with 2 decimals.
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from pathlib import Path

from wordfreq import zipf_frequency

# SCOWL categories (spelling variants) and size levels to include.
CATEGORIES = ("english-words", "english-upper", "english-contractions",
              "american-words", "american-upper",
              "british-words", "british-upper")
CORE_LEVELS = (10, 20, 35, 40, 50, 55, 60, 70)
# Larger, rarer levels: kept only if the word is actually used in modern text.
EXTRA_LEVELS = (80,)
EXTRA_MIN_ZIPF = 3.0

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "src/spell/data/en_words.tsv"


def read_list(path: Path) -> list[str]:
    text = path.read_bytes().decode("iso-8859-1")
    return [unicodedata.normalize("NFC", w.strip()) for w in text.splitlines() if w.strip()]


def keep(word: str) -> bool:
    if word.endswith("'s"):  # possessives roughly double the list for no benefit
        return False
    return all(c.isalpha() or c in "'-" for c in word)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scowl_dir", type=Path, help="extracted scowl-YYYY.MM.DD directory")
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    final = args.scowl_dir / "final"
    if not final.is_dir():
        print(f"error: {final} not found", file=sys.stderr)
        return 1

    words: set[str] = set()
    for cat in CATEGORIES:
        for lvl in CORE_LEVELS:
            p = final / f"{cat}.{lvl}"
            if p.exists():
                words.update(w for w in read_list(p) if keep(w))
    extra = 0
    for cat in CATEGORIES:
        for lvl in EXTRA_LEVELS:
            p = final / f"{cat}.{lvl}"
            if p.exists():
                for w in read_list(p):
                    if w not in words and keep(w) and zipf_frequency(w, "en") >= EXTRA_MIN_ZIPF:
                        words.add(w)
                        extra += 1

    # SCOWL lists some words in both forms ("Is", "is"); keep only the lowercase
    # one so that lookup keys stay unique. Capitalised-only words (English) stay.
    words = {w for w in words if w == w.lower() or w.lower() not in words}

    rows = sorted(((w, zipf_frequency(w, "en")) for w in words), key=lambda r: (-r[1], r[0]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# English word list derived from SCOWL 2020.12.07 (size <= 70, plus size-80 words\n")
        f.write("# with zipf >= 3.0); frequencies from wordfreq (zipf scale). See README for licenses.\n")
        for w, z in rows:
            f.write(f"{w}\t{z:.2f}\n")
    print(f"wrote {len(rows)} words ({extra} from level 80) to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
