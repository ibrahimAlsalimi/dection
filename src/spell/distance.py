"""Edit-distance functions.

The engine uses *optimal string alignment* (OSA) distance, also called the
restricted Damerau-Levenshtein distance: insertions, deletions, substitutions
and transpositions of two adjacent characters each cost 1, and no substring
is edited more than once. It differs from full Damerau-Levenshtein only on
inputs like ``ca -> abc`` (OSA 3, full DL 2), which is irrelevant for
single-word typo correction and makes the delete-based candidate index exact.

``weighted_distance`` is the same alignment with cheaper costs for error
types people make often when they know the word but not its spelling.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

VOWELS = frozenset("aeiouy")

# QWERTY neighbours, for fat-finger substitutions.
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_KEY_POS = {c: (r, i) for r, row in enumerate(_ROWS) for i, c in enumerate(row)}


def _adjacent_keys(a: str, b: str) -> bool:
    pa, pb = _KEY_POS.get(a), _KEY_POS.get(b)
    if pa is None or pb is None:
        return False
    return abs(pa[0] - pb[0]) <= 1 and abs(pa[1] - pb[1]) <= 1


# Costs used by weighted_distance. Plain edits cost 1.0.
COST_TRANSPOSE = 0.7      # becuase -> because
COST_DOUBLE = 0.5         # adding/removing a doubled letter: occured, writting
COST_VOWEL = 0.6          # vowel confusion: seperate, definately
COST_SAME_SOUND = 0.7     # c/k/s, i/y style confusions not covered above
COST_ADJACENT_KEY = 0.8   # keyboard slip
COST_ACCENT = 0.3         # missing/wrong diacritic: cafe -> café
_SAME_SOUND = {frozenset(p) for p in ("ck", "cs", "sz", "fv", "gj", "mn", "sc")}


def osa_distance(a: str, b: str, max_distance: int | None = None) -> int:
    """Optimal string alignment distance between ``a`` and ``b``.

    If ``max_distance`` is given and the distance exceeds it, returns
    ``max_distance + 1`` early.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if max_distance is not None and abs(la - lb) > max_distance:
        return max_distance + 1
    if la == 0:
        return lb
    if lb == 0:
        return la

    prev2: list[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ai = a[i - 1]
        row_min = i
        for j in range(1, lb + 1):
            bj = b[j - 1]
            cost = 0 if ai == bj else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ai == b[j - 2] and a[i - 2] == bj:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            if v < row_min:
                row_min = v
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1
        prev2, prev = prev, cur
    return prev[lb]


@lru_cache(maxsize=512)
def _base_letter(c: str) -> str:
    return unicodedata.normalize("NFD", c)[0]


def _sub_cost(x: str, y: str) -> float:
    if x == y:
        return 0.0
    if _base_letter(x) == _base_letter(y):
        return COST_ACCENT
    if x in VOWELS and y in VOWELS:
        return COST_VOWEL
    if frozenset((x, y)) in _SAME_SOUND:
        return COST_SAME_SOUND
    if _adjacent_keys(x, y):
        return COST_ADJACENT_KEY
    return 1.0


def weighted_distance(typed: str, word: str) -> float:
    """OSA alignment cost from ``typed`` to ``word`` with error-type weights.

    Inserting or deleting a letter next to an identical letter (a doubling
    mistake) is cheap, as are adjacent transpositions, vowel swaps and
    keyboard-neighbour slips. The result is always <= osa_distance.
    """
    a, b = typed, word
    la, lb = len(a), len(b)
    if a == b:
        return 0.0

    def indel(s: str, k: int) -> float:
        # cost of inserting/deleting s[k], cheap if it duplicates a neighbour
        c = s[k]
        if (k > 0 and s[k - 1] == c) or (k + 1 < len(s) and s[k + 1] == c):
            return COST_DOUBLE
        return 1.0

    # d[i][j] = cost of turning a[:i] into b[:j]
    d = [[0.0] * (lb + 1) for _ in range(la + 1)]
    for i in range(1, la + 1):
        d[i][0] = d[i - 1][0] + indel(a, i - 1)
    for j in range(1, lb + 1):
        d[0][j] = d[0][j - 1] + indel(b, j - 1)
    for i in range(1, la + 1):
        ai = a[i - 1]
        for j in range(1, lb + 1):
            bj = b[j - 1]
            v = min(
                d[i - 1][j] + indel(a, i - 1),       # delete typed char
                d[i][j - 1] + indel(b, j - 1),       # insert word char
                d[i - 1][j - 1] + _sub_cost(ai, bj),
            )
            if i > 1 and j > 1 and ai == b[j - 2] and a[i - 2] == bj and ai != bj:
                v = min(v, d[i - 2][j - 2] + COST_TRANSPOSE)
            d[i][j] = v
    return d[la][lb]
