import pytest

from spell.distance import osa_distance, weighted_distance


@pytest.mark.parametrize("a,b,d", [
    ("", "", 0), ("", "abc", 3), ("abc", "", 3), ("same", "same", 0),
    ("cat", "cats", 1),          # insertion
    ("cats", "cat", 1),          # deletion
    ("cat", "cut", 1),           # substitution
    ("teh", "the", 1),           # adjacent transposition
    ("recieve", "receive", 1),
    ("kitten", "sitting", 3),
    ("abcdef", "badcfe", 3),     # three separate transpositions
    ("café", "cafe", 1),         # unicode characters are single symbols
])
def test_osa(a, b, d):
    assert osa_distance(a, b) == d
    assert osa_distance(b, a) == d


def test_osa_is_restricted_damerau_levenshtein():
    # Documented choice: OSA, not full Damerau-Levenshtein (which gives 2).
    assert osa_distance("ca", "abc") == 3


def test_osa_max_distance_early_exit():
    assert osa_distance("abcdefgh", "zyxwvuts", max_distance=2) == 3
    assert osa_distance("a", "abcdef", max_distance=2) == 3
    assert osa_distance("recieve", "receive", max_distance=1) == 1


@pytest.mark.parametrize("typed,word", [
    ("occured", "occurred"), ("writting", "writing"), ("adress", "address"),  # doubling
    ("becuase", "because"), ("teh", "the"),                                    # transposition
    ("seperate", "separate"), ("definately", "definitely"),                    # vowels
    ("cafe", "café"),                                                           # accent
])
def test_common_errors_are_cheaper_than_a_plain_edit(typed, word):
    assert weighted_distance(typed, word) < osa_distance(typed, word)


@pytest.mark.parametrize("a,b", [("cat", "cut"), ("cat", "dog"), ("teh", "the"), ("", "abc"), ("abc", "abc")])
def test_weighted_never_exceeds_osa(a, b):
    assert 0 <= weighted_distance(a, b) <= osa_distance(a, b)
    assert weighted_distance(a, a) == 0
