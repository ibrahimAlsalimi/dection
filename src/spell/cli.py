"""Command-line entry point.

Exit codes (modelled on fzf):
  0    a word was printed (selected, corrected, or already correct)
  1    no suggestion found
  2    usage error, missing/unreadable dictionary, or no terminal
  3    word printed to stdout, but copying it to the clipboard failed
  130  interactive mode cancelled (Esc / Ctrl+C)
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .dictionary import DictionaryError, user_words_path
from .engine import DEFAULT_LIMIT, Speller

EXIT_OK, EXIT_NO_MATCH, EXIT_ERROR, EXIT_CLIPBOARD, EXIT_CANCEL = 0, 1, 2, 3, 130


def _positive_int(s: str) -> int:
    try:
        n = int(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {s!r}") from None
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="spell",
        description="Offline English spelling correction. With no WORD, opens an "
                    "interactive picker and prints the chosen word to stdout.",
        epilog=f"Custom words: one per line in {user_words_path()} "
               "(or the file named by $SPELL_USER_WORDS).\n"
               "Exit status: 0 word printed, 1 no suggestion, 2 error, "
               "3 clipboard failed (word still printed), 130 cancelled.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("word", nargs="?", metavar="WORD",
                   help="word to correct; prints the best correction (the word itself if correct)")
    p.add_argument("-s", "--suggest", action="store_true",
                   help="print ranked suggestions for WORD, one per line")
    p.add_argument("-n", "--limit", type=_positive_int, default=DEFAULT_LIMIT, metavar="N",
                   help=f"maximum number of suggestions (default {DEFAULT_LIMIT})")
    p.add_argument("-c", "--copy", action="store_true",
                   help="also copy the resulting word to the clipboard")
    p.add_argument("--no-user-words", action="store_true",
                   help="ignore the custom word list")
    p.add_argument("-V", "--version", action="version", version=f"spell {__version__}")
    return p


def _copy(word: str) -> int:
    from .clipboard import ClipboardError, copy

    try:
        copy(word)
    except ClipboardError as e:
        print(f"spell: {e}", file=sys.stderr)
        return EXIT_CLIPBOARD
    return EXIT_OK


def _emit(word: str, copy: bool) -> int:
    print(word, flush=True)
    return _copy(word) if copy else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.suggest and args.word is None:
        parser.error("--suggest needs a WORD")

    try:
        speller = Speller.default(use_user_words=not args.no_user_words)
    except DictionaryError as e:
        print(f"spell: {e}", file=sys.stderr)
        return EXIT_ERROR

    if args.word is not None:
        results = speller.suggest(args.word, args.limit if args.suggest else 1)
        if not results:
            print(f"spell: no suggestions for {args.word!r}", file=sys.stderr)
            return EXIT_NO_MATCH
        if args.suggest:
            print("\n".join(s.word for s in results), flush=True)
            return _copy(results[0].word) if args.copy else EXIT_OK
        return _emit(results[0].word, args.copy)

    from .tui import NoTerminalError, run
    try:
        chosen = run(speller, args.limit)
    except NoTerminalError as e:
        print(f"spell: {e}; use 'spell WORD' or 'spell --suggest WORD' in scripts", file=sys.stderr)
        return EXIT_ERROR
    if chosen is None:
        return EXIT_CANCEL
    return _emit(chosen, args.copy)


if __name__ == "__main__":
    raise SystemExit(main())
