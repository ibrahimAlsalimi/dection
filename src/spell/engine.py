"""Spelling correction engine: candidate retrieval + ranking.

Candidate retrieval (see README "Design" for the reasoning):

* Every dictionary word is indexed under itself and each of its single-
  character deletions (a SymSpell-style delete index with max distance 1).
  Two strings are within OSA distance 1 exactly when one of them, or one of
  their single deletions, equals the other's or one of its single deletions,
  so looking up the input and its deletions finds all distance-1 words.
* Distance-2 words are found by expanding the input by one edit (deletes,
  transpositions, substitutions, inserts) and doing the distance-1 lookup for
  each expansion. This keeps the index small (no distance-2 deletes stored)
  and costs a few thousand hash lookups per query.
* The index is stored compactly as one sorted ``array('Q')`` of
  ``crc32(key) << 32 | word_id`` values and searched with ``bisect``. Hash
  collisions only add false candidates, which the exact distance check
  removes. It is cached on disk, so it is built once per dictionary version.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unicodedata
from array import array
from bisect import bisect_left
from collections.abc import Iterable, Iterator
from pathlib import Path
from zlib import crc32

from . import dictionary as dictmod
from .dictionary import Dictionary, normalize
from .distance import osa_distance
from .ranking import Suggestion, match_case, score, sort_key

INDEX_VERSION = 1
DEFAULT_LIMIT = 8
MAX_WORD_LENGTH = 40   # longer input: exact lookup only
SHORT_WORD = 3         # inputs this short are searched at distance 1 only
_MASK = 0xFFFFFFFF
_ALLOWED_PUNCT = frozenset("'-")


def _deletes(word: str) -> Iterator[str]:
    for i in range(len(word)):
        yield word[:i] + word[i + 1:]


def _edits1(word: str, alphabet: str) -> set[str]:
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out = {a + b[1:] for a, b in splits if b}
    out.update(a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1)
    out.update(a + c + b[1:] for a, b in splits if b for c in alphabet)
    out.update(a + c + b for a, b in splits for c in alphabet)
    return out


def _hash(key: str) -> int:
    return crc32(key.encode("utf-8"))


def is_word_like(text: str) -> bool:
    """True if ``text`` looks like a single word: letters, apostrophes, hyphens."""
    return bool(text) and any(c.isalpha() for c in text) and all(
        c.isalpha() or c in _ALLOWED_PUNCT for c in text)


class DeleteIndex:
    """Sorted array of (crc32(key) << 32 | id) for each word and its deletes."""

    def __init__(self, data: array):
        self.data = data

    @classmethod
    def build(cls, keys: list[str]) -> DeleteIndex:
        vals: set[int] = set()
        for wid, key in enumerate(keys):
            vals.add(_hash(key) << 32 | wid)
            for d in _deletes(key):
                vals.add(_hash(d) << 32 | wid)
        return cls(array("Q", sorted(vals)))

    def lookup(self, key: str) -> Iterator[int]:
        data = self.data
        h = _hash(key) << 32
        i = bisect_left(data, h)
        n = len(data)
        while i < n:
            v = data[i]
            if v - h > _MASK:
                break
            yield v & _MASK
            i += 1

    # -- persistence -------------------------------------------------------

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".index-")
        try:
            with os.fdopen(fd, "wb") as f:
                self.data.tofile(f)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def load(cls, path: Path) -> DeleteIndex:
        data = array("Q")
        size = path.stat().st_size
        if size % data.itemsize:
            raise ValueError("corrupt index file")
        with path.open("rb") as f:
            data.fromfile(f, size // data.itemsize)
        return cls(data)


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "spell"


class Speller:
    """Single-word spelling corrector over a Dictionary."""

    def __init__(self, d: Dictionary, *, cache: Path | None | bool = True):
        self.dict = d
        keys = list(d.entries)
        self.main_keys = keys[: d.main_count]
        self.extra_keys = keys[d.main_count:]
        self.index = self._load_index(cache)
        # Small, plain index for user-added words.
        self.extra_index: dict[str, list[str]] = {}
        for k in self.extra_keys:
            for dk in (k, *_deletes(k)):
                self.extra_index.setdefault(dk, []).append(k)
        chars = {c for k in keys for c in k}
        self.alphabet = "".join(sorted(chars))

    @classmethod
    def default(cls, *, use_user_words: bool = True, cache: bool = True) -> Speller:
        return cls(dictmod.load(use_user_words=use_user_words), cache=cache)

    # -- index -------------------------------------------------------------

    def _index_path(self, base: Path) -> Path:
        h = hashlib.blake2b(digest_size=12)
        h.update(f"v{INDEX_VERSION}:{sys.byteorder}\n".encode())
        h.update("\n".join(self.main_keys).encode("utf-8"))
        return base / f"index-{h.hexdigest()}.bin"

    def _load_index(self, cache: Path | None | bool) -> DeleteIndex:
        if cache is False or cache is None:
            return DeleteIndex.build(self.main_keys)
        path = self._index_path(cache_dir() if cache is True else Path(cache))
        try:
            return DeleteIndex.load(path)
        except (OSError, ValueError):
            pass
        idx = DeleteIndex.build(self.main_keys)
        try:
            idx.save(path)
        except OSError:
            pass  # read-only home etc.: keep working without a cache
        return idx

    def _candidates_d1(self, query_keys: Iterable[str]) -> set[str]:
        out: set[str] = set()
        main = self.main_keys
        extra = self.extra_index
        for q in query_keys:
            for wid in self.index.lookup(q):
                if wid < len(main):
                    out.add(main[wid])
            if extra:
                out.update(extra.get(q, ()))
        return out

    def candidates(self, key: str, max_distance: int) -> set[str]:
        """Dictionary keys that may be within ``max_distance`` (<= 2) of ``key``.

        A superset: callers must verify with osa_distance.
        """
        probes = {key, *_deletes(key)}
        if max_distance >= 2:
            for e in _edits1(key, self.alphabet):
                probes.add(e)
                probes.update(_deletes(e))
        return self._candidates_d1(probes)

    # -- public API ----------------------------------------------------------

    def suggest(self, word: str, limit: int = DEFAULT_LIMIT) -> list[Suggestion]:
        """Ranked corrections for ``word`` (best first), at most ``limit``.

        An exact dictionary match is always first. Returns [] for empty or
        non-word input and when nothing is within reach.
        """
        typed = unicodedata.normalize("NFC", word.strip())
        key = normalize(typed)
        if not key or limit <= 0:
            return []
        entries = self.dict.entries
        if not is_word_like(key) or len(key) > MAX_WORD_LENGTH:
            e = entries.get(key)
            return [Suggestion(match_case(typed, e.display), 0, 0.0, e.zipf, e.zipf)] if e else []

        max_d = 1 if len(key) <= SHORT_WORD else 2
        results: list[Suggestion] = []
        for cand in self.candidates(key, max_d):
            d = osa_distance(key, cand, max_d)
            if d > max_d:
                continue
            e = entries[cand]
            cost, s = score(key, cand, d, e.zipf)
            results.append(Suggestion(match_case(typed, e.display), d, cost, e.zipf, s))
        results.sort(key=sort_key)
        return results[:limit]

    def correct(self, word: str) -> Suggestion | None:
        """The single best correction (the word itself if it is spelled right)."""
        s = self.suggest(word, 1)
        return s[0] if s else None

    def is_known(self, word: str) -> bool:
        return normalize(word) in self.dict.entries
