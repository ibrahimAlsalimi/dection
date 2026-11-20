import pytest

from spell import dictionary
from spell.dictionary import DictionaryError
from spell.distance import osa_distance
from spell.engine import DeleteIndex, Speller


def top(speller, word):
    s = speller.correct(word)
    return s.word if s else None


@pytest.mark.parametrize("typo,expected", [
    ("recieve", "receive"), ("teh", "the"), ("adress", "address"),
    ("enviroment", "environment"), ("definately", "definitely"),
    ("langauge", "language"), ("becuase", "because"), ("seperate", "separate"),
    ("occured", "occurred"), ("writting", "writing"),
])
def test_required_corrections(speller, typo, expected):
    assert top(speller, typo) == expected


@pytest.mark.parametrize("typo,expected", [
    ("accomodate", "accommodate"), ("embarass", "embarrass"), ("tommorow", "tomorrow"),
    ("untill", "until"), ("wierd", "weird"), ("thier", "their"), ("beleive", "believe"),
    ("goverment", "government"), ("neccessary", "necessary"), ("succesful", "successful"),
])
def test_more_common_misspellings(speller, typo, expected):
    assert top(speller, typo) == expected


def test_empty_and_blank_input(speller):
    assert speller.suggest("") == []
    assert speller.suggest("   ") == []
    assert speller.correct("") is None


@pytest.mark.parametrize("word", ["the", "receive", "environment", "because", "don't", "isn't"])
def test_correct_words_come_first(speller, word):
    s = speller.suggest(word)
    assert s[0].word == word and s[0].exact
    assert speller.is_known(word)


def test_mixed_capitalization(speller):
    assert top(speller, "Recieve") == "Receive"
    assert top(speller, "RECIEVE") == "RECEIVE"
    assert top(speller, "rEcIeVe") == "receive"
    assert top(speller, "THE") == "THE"
    assert top(speller, "monday") == "Monday"     # proper capitalisation is kept


def test_very_short_words(speller):
    assert top(speller, "a") == "a"
    assert top(speller, "hte") == "the"
    s = speller.suggest("xq")
    assert all(x.distance <= 1 for x in s)       # short input: distance 1 only


def test_long_words(speller):
    assert top(speller, "internationaly") == "internationally"
    assert top(speller, "incomprehensable") == "incomprehensible"
    assert top(speller, "responsibilites") == "responsibilities"


def test_very_long_input_is_bounded(speller):
    assert speller.suggest("a" * 500) == []


def test_unknown_words_get_no_fabricated_suggestions(speller):
    assert speller.suggest("xqzvwk") == []
    assert speller.suggest("zzzzzzzzqqq") == []
    for s in speller.suggest("blorft"):
        assert s.distance <= 2


def test_equally_plausible_candidates_are_deterministic(speller):
    a = [s.word for s in speller.suggest("cst")]
    b = [s.word for s in speller.suggest("cst")]
    assert a == b and len(a) > 1
    # results are ordered by score, best first
    scores = [s.score for s in speller.suggest("cst") if not s.exact]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize("text", ["123", "hello world", "foo_bar", "a+b", "!!!", "--", "''", "😀"])
def test_nonalphabetic_input(speller, text):
    assert speller.suggest(text) == []


def test_unicode_input(speller):
    assert top(speller, "café") == "café"
    assert "café" in [s.word for s in speller.suggest("cafe")]
    assert top(speller, "naïve") == "naive"     # dictionary has the unaccented form
    assert top(speller, "cafe\u0301") == "café"    # decomposed accent is NFC-normalised
    assert top(speller, "don’t") == "don't"   # typographic apostrophe


def test_limit(speller):
    assert len(speller.suggest("recieve", limit=3)) == 3
    assert speller.suggest("recieve", limit=0) == []
    assert len(speller.suggest("recieve")) <= 8


def test_missing_dictionary_file(tmp_path):
    with pytest.raises(DictionaryError, match="not found"):
        dictionary.load(tmp_path / "nope.tsv")


def test_missing_user_word_file_is_fine(tmp_path):
    d = dictionary.load(user_path=tmp_path / "nope.txt")
    assert "the" in d


def test_user_words(tmp_path):
    words = tmp_path / "words.txt"
    words.write_text("# my words\nKubernetes\nPostgreSQL\nmicrocontroller\nsystemd 3.5\nreceive\n")
    d = dictionary.load(user_path=words)
    sp = Speller(d, cache=tmp_path / "cache")
    assert top(sp, "kubernetes") == "Kubernetes"
    assert top(sp, "kubernets") == "Kubernetes"
    assert top(sp, "postgressql") == "PostgreSQL"
    assert top(sp, "microcontroler") == "microcontroller"
    assert top(sp, "systemd") == "systemd"
    assert d.entries["receive"].zipf > 4.5          # user list never lowers frequency
    assert d.main_count < len(d.entries)            # original dictionary untouched


def test_index_cache_roundtrip(tmp_path):
    d = dictionary.load(use_user_words=False)
    sp1 = Speller(d, cache=tmp_path)
    files = list(tmp_path.glob("index-*.bin"))
    assert len(files) == 1
    sp2 = Speller(d, cache=tmp_path)          # loads from cache
    assert sp2.index.data == sp1.index.data
    files[0].write_bytes(b"123")              # corrupt cache is rebuilt
    sp3 = Speller(d, cache=tmp_path)
    assert sp3.index.data == sp1.index.data


def test_delete_index_lookup():
    idx = DeleteIndex.build(["cat", "cart"])
    assert set(idx.lookup("cat")) == {0, 1}   # "cat" is itself and a delete of "cart"
    assert set(idx.lookup("ct")) == {0}
    assert set(idx.lookup("dog")) == set()


@pytest.mark.parametrize("typo", ["recieve", "embarass", "abcdefg", "fluor", "qwerty"])
def test_candidate_retrieval_is_complete(speller, typo):
    """Index search finds every dictionary word a brute-force scan finds."""
    brute = {k for k in speller.dict.entries
             if abs(len(k) - len(typo)) <= 2 and osa_distance(typo, k, 2) <= 2}
    found = {k for k in speller.candidates(typo, 2) if osa_distance(typo, k, 2) <= 2}
    assert found == brute
