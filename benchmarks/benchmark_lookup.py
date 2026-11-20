#!/usr/bin/env python3
"""Benchmark startup and per-query latency of the spelling engine.

    python benchmarks/benchmark_lookup.py

Reports: dictionary load time, index build time (cold) vs cache load (warm),
index memory, per-query latency over a set of misspellings and over every
prefix of them (what the interactive UI does while you type), and the
latency of a full `spell WORD` process.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

from spell import dictionary
from spell.engine import Speller

WORDS = """recieve teh adress enviroment definately langauge becuase seperate occured
writting accomodate embarass tommorow untill wierd thier beleive goverment neccessary
succesful the receive internationaly incomprehensable responsibilites a xqzvwk
acknowledgement occurence existance independant maintainance pronounciation""".split()


def ms(sec: float) -> str:
    return f"{sec * 1000:7.2f} ms"


def summarize(name: str, samples: list[float]) -> None:
    s = sorted(samples)
    p95 = s[int(len(s) * 0.95) - 1] if len(s) >= 20 else s[-1]
    print(f"{name:34} n={len(s):4}  median {ms(statistics.median(s))}  "
          f"p95 {ms(p95)}  max {ms(s[-1])}")


def main() -> None:
    print(f"Python {sys.version.split()[0]} on {sys.platform}")
    t = time.perf_counter()
    d = dictionary.load(use_user_words=False)
    print(f"{'dictionary load':34} {ms(time.perf_counter() - t)}  ({len(d)} words)")

    with tempfile.TemporaryDirectory() as tmp:
        t = time.perf_counter()
        Speller(d, cache=Path(tmp))
        print(f"{'index build + save (cold)':34} {ms(time.perf_counter() - t)}")
        t = time.perf_counter()
        sp = Speller(d, cache=Path(tmp))
        print(f"{'index load from cache (warm)':34} {ms(time.perf_counter() - t)}")
        size = sum(f.stat().st_size for f in Path(tmp).iterdir())
        print(f"{'index cache file':34} {size / 1e6:7.2f} MB  ({len(sp.index.data)} entries)")

    tracemalloc.start()
    d2 = dictionary.load(use_user_words=False)
    after_dict = tracemalloc.get_traced_memory()[0]
    with tempfile.TemporaryDirectory() as tmp:
        Speller(d2, cache=Path(tmp))
        sp2 = Speller(d2, cache=Path(tmp))
    total = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    del sp2
    print(f"{'memory: dictionary':34} {after_dict / 1e6:7.1f} MB")
    print(f"{'memory: dictionary + index':34} {total / 1e6:7.1f} MB")

    for w in WORDS:  # warm-up
        sp.suggest(w)
    full = []
    for _ in range(5):
        for w in WORDS:
            t = time.perf_counter()
            sp.suggest(w)
            full.append(time.perf_counter() - t)
    summarize("query, whole words", full)

    typing = []
    for w in WORDS:
        for i in range(1, len(w) + 1):
            t = time.perf_counter()
            sp.suggest(w[:i])
            typing.append(time.perf_counter() - t)
    summarize("query, every prefix (typing)", typing)

    env = dict(os.environ)
    proc = []
    for _ in range(5):
        t = time.perf_counter()
        subprocess.run([sys.executable, "-m", "spell", "recieve"], capture_output=True, env=env, check=True)
        proc.append(time.perf_counter() - t)
    summarize("process: spell recieve (warm cache)", proc)


if __name__ == "__main__":
    main()
