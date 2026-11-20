from spell.ranking import EDIT_WEIGHT, Suggestion, match_case, score, sort_key


def S(word, d, cost, zipf):
    return Suggestion(word, d, cost, zipf, zipf - EDIT_WEIGHT * cost)


def test_exact_match_first_even_if_rare():
    items = [S("the", 1, 1.0, 7.7), S("teh", 0, 0.0, 1.0)]
    assert sorted(items, key=sort_key)[0].word == "teh"


def test_frequency_breaks_ties_between_equal_edits():
    items = [S("relieve", 1, 1.0, 3.8), S("receive", 1, 1.0, 4.9)]
    assert [s.word for s in sorted(items, key=sort_key)] == ["receive", "relieve"]


def test_frequency_does_not_overwhelm_similarity():
    # a 100x more common word one extra edit away must still lose
    close, far = S("close", 1, 1.0, 3.0), S("far", 2, 2.0, 5.0)
    assert sorted([far, close], key=sort_key)[0] is close


def test_deterministic_alphabetical_tiebreak():
    a, b = S("bat", 1, 1.0, 3.0), S("cat", 1, 1.0, 3.0)
    assert sorted([b, a], key=sort_key) == [a, b]
    assert sorted([a, b], key=sort_key) == [a, b]


def test_score_exact_has_no_cost():
    assert score("the", "the", 0, 7.0) == (0.0, 7.0)
    cost, s = score("teh", "the", 1, 7.0)
    assert 0 < cost < 1 and s < 7.0


def test_match_case():
    assert match_case("recieve", "receive") == "receive"
    assert match_case("Recieve", "receive") == "Receive"
    assert match_case("RECIEVE", "receive") == "RECEIVE"
    assert match_case("rEcIeVe", "receive") == "receive"
    assert match_case("english", "English") == "English"
    assert match_case("POSTGRESQL", "PostgreSQL") == "PostgreSQL"
    assert match_case("I", "a") == "A"
