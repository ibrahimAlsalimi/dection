# spell

A fast, offline English spelling corrector for the terminal. Type a word you
are not sure how to spell, pick the right spelling from a live, ranked list
(fzf-style), and get it on stdout or in your clipboard.

```text
  spell - English Spelling Correction
  > recieve
  8 suggestions
  > receive
    relieve
    received
    believe
    receives
    receiver
    deceive
    revive
  ↑↓ Navigate | Enter Select | Tab Complete | Esc Exit
```

It is a single-word spelling tool. It does not check grammar, rewrite sentences,
translate, or talk to any network service.

## Install

Requires Python 3.11+ (tested on 3.14, Linux).

```bash
pipx install .            # recommended: isolated, puts `spell` on PATH
# or
pip install .             # into the current environment
# development
python -m venv .venv && .venv/bin/pip install -e '.[test]'
```

The only runtime dependency is `prompt_toolkit`. The dictionary ships inside
the package. On the first run, `spell` builds a lookup index in about 1 s and
caches it in `$XDG_CACHE_HOME/spell/` (default `~/.cache/spell/`). After that,
it starts in about 0.2 s.

## Usage

```bash
spell                       # interactive picker; prints the chosen word
spell recieve               # → receive   (best correction, non-interactive)
spell --suggest recieve     # ranked suggestions, one per line
spell --suggest -n 3 teh    # at most 3 suggestions
spell --limit 5             # interactive, show 5 suggestions
spell --copy                # interactive, also copy the choice to the clipboard
spell --copy recieve        # non-interactive + clipboard
spell --help
```

The UI is drawn on the terminal (`/dev/tty`), never on stdout, so this works:

```bash
word=$(spell) && echo "you picked $word"
```

### Keys (interactive)

| Key | Action |
|---|---|
| typing | suggestions update on every keystroke |
| ↑ / ↓ (also Ctrl+P / Ctrl+N) | move the highlight (wraps around) |
| Enter | print the highlighted word and exit |
| Tab | put the highlighted word in the input field |
| Ctrl+U | clear the input |
| Esc / Ctrl+C / Ctrl+G | cancel |

### Non-interactive behavior

* A correctly spelled word is printed unchanged, because exact matches always rank first.
* A misspelled word prints its best correction.
* If no dictionary word is within reach (2 edits, or 1 edit for words of 3
  letters or fewer), nothing goes to stdout, a message goes to stderr, and the exit status is 1.
  Input that is not a word (digits, spaces, symbols) is handled the same way. `spell` never makes up a suggestion.
* Capitalization carries over: `Recieve` → `Receive`, `RECIEVE` → `RECEIVE`.
  Words with their own capitals stay that way (`monday` → `Monday`).

### Exit status

| Code | Meaning |
|---|---|
| 0 | a word was printed |
| 1 | no suggestion found |
| 2 | usage error, dictionary missing or unreadable, or no terminal for interactive mode |
| 3 | the word was printed to stdout, but copying it to the clipboard failed (the reason is on stderr) |
| 130 | interactive mode cancelled |

`--copy` uses `wl-copy` on Wayland, then `xclip` or `xsel` on X11 (`pbcopy` on macOS, `clip` on Windows).

### Custom words

Add your own vocabulary, one word per line, to `~/.config/spell/words.txt`
(`$XDG_CONFIG_HOME/spell/words.txt`, or any file named by `$SPELL_USER_WORDS`):

```text
# my words
Kubernetes
PostgreSQL
microcontroller
systemd 4.5      # optional frequency on the Zipf scale (default 4.0)
```

Your capitalization is kept (`kubernets` → `Kubernetes`). The bundled
dictionary is never modified. Custom words are indexed at startup, so they take
effect on the next run. Use `--no-user-words` to ignore the file.

## Design

```text
src/spell/
  cli.py         argument parsing, exit codes, stdout/stderr discipline
  tui.py         prompt_toolkit picker (UI only; calls Speller.suggest)
  engine.py      Speller: input validation, candidate retrieval, index cache
  distance.py    OSA distance + weighted distance for common error types
  ranking.py     scoring, ordering, capitalization transfer
  dictionary.py  word-list loading, user words, normalization
  clipboard.py   platform clipboard tools
  data/          en_words.tsv (word, Zipf frequency) + data licenses
scripts/build_dictionary.py   regenerates en_words.tsv from SCOWL + wordfreq
benchmarks/benchmark_lookup.py
```

The engine has no UI dependencies:
`Speller.default().suggest("recieve")` returns ranked `Suggestion` objects.

### Edit distance: OSA, not full Damerau-Levenshtein

`distance.osa_distance` implements **optimal string alignment** distance (restricted
Damerau-Levenshtein). It counts insertion, deletion, substitution and adjacent
transposition as one edit each, and edits no substring twice. It differs from full
Damerau-Levenshtein only on cases like `ca → abc` (OSA 3, full DL 2), which never
matter for typos. It also matches exactly what the delete-based index can
retrieve, so retrieval and verification agree.

### Candidate retrieval

Options considered:

| Approach | Verdict |
|---|---|
| Full scan + distance | ~126k distance computations per keystroke in Python: seconds. No. |
| Norvig: generate all edits of the input | Distance 1 is cheap. Distance 2 means about 250k strings per query: 100+ ms. |
| BK-tree | Pure-Python queries at distance 2 still visit 10–20% of nodes: too slow. |
| SymSpell, deletes up to distance 2 | Fast, but needs several million keys. Even the distance-1 delete index as a Python dict measured about 110 MB. |
| **Delete index at distance 1 + one-edit expansion of the input** | **chosen** |

Every word is indexed under itself and each of its single-character deletions:
1.2M keys. Two strings are within OSA distance 1 exactly when they share such a
key, so looking up the input and its deletions finds every distance-1 word. For
distance 2, the input is expanded by one edit (deletions, transpositions,
substitutions, insertions), and each variant gets a distance-1 lookup. That is
a few thousand lookups per query. Candidates are then verified with the exact
OSA distance. A test checks that the result matches a brute-force scan.

Storing 1.2M keys as Python strings would cost about 110 MB. The index is
stored instead as one sorted `array('Q')` of `crc32(key) << 32 | word_id`, searched with
`bisect`. That takes 9.6 MB in memory and 9.6 MB on disk. Hash collisions only add false candidates,
which verification removes. The array is written to the cache directory under a
name derived from a hash of the word list, so it is built once per dictionary
version and loaded with one `fromfile` call (about 27 ms). A missing,
corrupt or unwritable cache falls back to building in memory.

Inputs of 3 letters or fewer are searched at distance 1 only. At distance 2,
nearly every short word would match. Inputs over 40 characters are only looked up exactly.

### Ranking

```text
score = zipf_frequency − 3 × weighted_edit_distance
```

* Exact matches always come first.
* `weighted_edit_distance` is the OSA alignment with cheaper costs for errors
  people commonly make when they know a word but not its spelling:
  * adding or dropping a doubled letter (`occured`, `writting`, `adress`): 0.5
  * vowel confusion (`seperate`, `definately`): 0.6
  * adjacent transposition (`becuase`, `teh`): 0.7
  * similar-sounding consonants (c/k/s, …): 0.7
  * QWERTY-neighbor slip: 0.8
  * missing or wrong accent (`cafe` → `café`): 0.3
* With a weight of 3, one full edit is worth a 1000× frequency difference.
  Frequency decides between similarly close candidates, but cannot lift a
  clearly worse spelling match over a good one (`writting` → `writing`, not
  `written`).
* Ties are broken by raw OSA distance, then frequency, then alphabetical order,
  so the output is deterministic.

No correction is hard-coded. All the test words are corrected by the general
mechanism above.

## Dictionary

`src/spell/data/en_words.tsv`: **126,315 words**, 1.9 MB, `word<TAB>zipf`.

* **Word list: [SCOWL](http://wordlist.aspell.net/) 2020.12.07** by Kevin
  Atkinson, the list behind aspell/hunspell English dictionaries. It includes the
  `english`, `american` and `british` word, capitalized-word and contraction lists at
  size ≤ 70 (the size recommended for spell checkers), plus size-80 words
  that are common in modern text (Zipf ≥ 3). It includes inflections (plurals,
  verb forms) and both US and UK spellings. Possessives (`'s`) are dropped.
  SCOWL is curated and contains no common misspellings. That matters: large
  scraped lists contain `enviroment` and `langauge`, which would make typos look
  correct. License: permissive, MIT-like (full text in `data/LICENSE-DATA.txt`).
* **Frequencies: [wordfreq](https://github.com/rspeer/wordfreq) 3.1.1** by
  Robyn Speer (Zipf scale: log10 of occurrences per billion words). The data is
  CC BY-SA 4.0, so the frequency column is too. Words wordfreq does not know get Zipf 1.0.

**Updating:** download a SCOWL release, `pip install wordfreq`, then run
`python scripts/build_dictionary.py path/to/scowl-YYYY.MM.DD`. The index cache
rebuilds automatically, because its file name is derived from the word list.

The `data/words.txt` file at the repository root is not used. It is the dwyl
`english-words` list. It has no frequencies, so it can't rank suggestions, and it
contains misspellings such as `enviroment`, `langauge` and `Teh`.

## Performance

Measured with `python benchmarks/benchmark_lookup.py` on an Intel i7-11370H
running Python 3.14.10 on Linux:

| Measurement | Result |
|---|---|
| Dictionary load | 121 ms |
| Index build (first run only) | 1.13 s |
| Index load from cache | 27 ms |
| Memory, dictionary + index (tracemalloc) | 36 MB |
| Query, whole misspelled words (n=165) | median 8.0 ms, p95 27.7 ms, max 32.4 ms |
| Query, every prefix while typing (n=283) | median 4.7 ms, p95 16.2 ms, max 33.9 ms |
| `spell recieve` whole process, warm cache | 205 ms (mostly interpreter start and dictionary load) |

All interactive updates measured were under the 50 ms target. Queries for long
words (12+ letters) are the slowest, because the one-edit expansion grows with length.
No disk access happens per keystroke.

## Tests

```bash
.venv/bin/pytest -q          # 107 tests
```

The tests cover:

* the 10 required corrections plus 10 more common misspellings
* empty input, correct words, mixed case, very short and long words, unknown and nonalphabetic input
* Unicode (NFC, accents, typographic apostrophes) and deterministic ties
* a missing dictionary and user words
* the index cache round trip and corruption, and index completeness against a brute-force scan
* the picker logic (typing, wrap-around navigation, Tab)
* CLI stdout cleanliness, exit codes and clipboard failure

## Limitations

* Distance is capped at 2 edits (1 for words of 3 letters or fewer). Severe misspellings
  like `fonetik` → `phonetic` are out of reach. There is no phonetic matching.
* Ranking uses each word in isolation, with no sentence context. `thier` → `their` is
  right, but `form`/`from` mix-ups are not detected, because both are real words.
* Real-word errors (`calender` is in SCOWL as a real word) are reported as correct.
* Hyphenated compounds and phrases are not in the dictionary (`alot` suggests
  `lot`, not `a lot`).
* Interactive mode needs a terminal (`/dev/tty`). In pipelines, use `spell WORD`
  or `--suggest`.
* Tested on Linux only. The code avoids Linux-only APIs, except that clipboard
  and `/dev/tty` support on macOS/Windows is untested.
