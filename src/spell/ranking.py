"""Scoring and ordering of candidate corrections.

score = zipf_frequency - EDIT_WEIGHT * weighted_edit_distance

With EDIT_WEIGHT = 3, one full edit is worth a 1000x frequency difference, so
frequency decides between candidates that are similarly close to the input,
but cannot drag a much worse spelling match above a good one. Cheap error
types (transpositions, doubled letters, vowel swaps, keyboard neighbours)
come from distance.weighted_distance.
"""

from __future__ import annotations

from dataclasses import dataclass

from .distance import weighted_distance

EDIT_WEIGHT = 3.0


@dataclass(frozen=True, slots=True)
class Suggestion:
    word: str        # display form, case-adjusted to the input
    distance: int    # OSA edit distance from the input
    cost: float      # weighted edit distance
    zipf: float      # word frequency (Zipf scale)
    score: float

    @property
    def exact(self) -> bool:
        return self.distance == 0


def score(typed: str, key: str, osa: int, zipf: float) -> tuple[float, float]:
    """Return (weighted_cost, score) for candidate ``key`` of input ``typed``."""
    cost = 0.0 if osa == 0 else weighted_distance(typed, key)
    return cost, zipf - EDIT_WEIGHT * cost


def sort_key(s: Suggestion) -> tuple:
    # exact match first, then best score, then fewer raw edits, then more
    # frequent, then alphabetical: fully deterministic.
    return (not s.exact, -round(s.score, 6), s.distance, -s.zipf, s.word.casefold(), s.word)


def match_case(typed: str, display: str) -> str:
    """Carry the input's capitalisation over to a suggestion.

    Words with their own capitals (English, PostgreSQL) keep them. Otherwise
    ALL-CAPS input gives an all-caps suggestion and Capitalised input a
    capitalised one.
    """
    if display != display.lower():
        return display
    letters = [c for c in typed if c.isalpha()]
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return display.upper()
    if letters and letters[0].isupper():
        return display[:1].upper() + display[1:]
    return display
