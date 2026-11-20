"""Loading the bundled word list and the optional user word list."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

# Zipf value for words that appear in the curated list but are too rare for
# wordfreq to have a number. Below every word wordfreq does know about.
UNKNOWN_FREQ_ZIPF = 1.0
# Default Zipf value for user-defined words: roughly "a reasonably common word",
# so that custom vocabulary competes with, but does not drown, ordinary words.
USER_WORD_ZIPF = 4.0


class DictionaryError(Exception):
    """Raised when a dictionary file is missing or unreadable."""


def normalize(word: str) -> str:
    """Lookup key for a word: NFC-normalised, case-folded, typographic
    apostrophes replaced, surrounding whitespace stripped."""
    word = unicodedata.normalize("NFC", word.strip()).replace("’", "'")
    return word.casefold()


@dataclass(slots=True)
class Entry:
    display: str   # spelling to show, e.g. "English", "PostgreSQL", "receive"
    zipf: float    # log10 frequency per billion words


@dataclass
class Dictionary:
    entries: dict[str, Entry] = field(default_factory=dict)
    # The first ``main_count`` keys of ``entries`` (insertion order) come from
    # the main word list; any after that were added by the user's word list.
    main_count: int = 0

    def add(self, word: str, zipf: float, *, override: bool = False) -> None:
        key = normalize(word)
        if not key:
            return
        cur = self.entries.get(key)
        if cur is None:
            self.entries[key] = Entry(word.strip(), zipf)
        elif override:
            # user word: take the user's spelling, never lower the frequency
            self.entries[key] = Entry(word.strip(), max(zipf, cur.zipf))
        elif zipf > cur.zipf:
            self.entries[key] = Entry(word.strip(), zipf)

    def __contains__(self, word: str) -> bool:
        return normalize(word) in self.entries

    def __len__(self) -> int:
        return len(self.entries)


def bundled_path() -> Path:
    return Path(str(resources.files("spell") / "data" / "en_words.tsv"))


def user_words_path() -> Path:
    """$SPELL_USER_WORDS, else $XDG_CONFIG_HOME/spell/words.txt."""
    env = os.environ.get("SPELL_USER_WORDS")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "spell" / "words.txt"


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        raise DictionaryError(f"dictionary file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as e:
        raise DictionaryError(f"cannot read dictionary file {path}: {e}") from None


def load_word_file(d: Dictionary, path: Path, default_zipf: float, *, override: bool = False) -> int:
    """Add entries from a ``word[<TAB or space>zipf]`` file; ``#`` starts a comment.

    Returns the number of lines added.
    """
    n = 0
    for line in _read_lines(path):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        word, zipf = parts[0], default_zipf
        if len(parts) > 1:
            try:
                zipf = float(parts[1])
            except ValueError:
                pass
        if zipf <= 0:
            zipf = UNKNOWN_FREQ_ZIPF
        d.add(word, zipf, override=override)
        n += 1
    return n


def load(path: Path | None = None, user_path: Path | None = None, *, use_user_words: bool = True) -> Dictionary:
    """Load the main dictionary plus (if present) the user's own word list.

    A missing main dictionary raises DictionaryError; a missing user word
    list is normal and silently ignored.
    """
    d = Dictionary()
    load_word_file(d, path or bundled_path(), UNKNOWN_FREQ_ZIPF)
    d.main_count = len(d.entries)
    if use_user_words:
        up = user_path or user_words_path()
        if up.exists():
            load_word_file(d, up, USER_WORD_ZIPF, override=True)
    return d
