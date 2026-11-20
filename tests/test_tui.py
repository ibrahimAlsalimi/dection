from spell.tui import Picker


def test_picker_updates_while_typing(speller):
    p = Picker(speller, limit=5)
    assert p.items == [] and p.current is None
    p.buffer.insert_text("recieve")
    assert p.current == "receive"
    assert len(p.items) == 5


def test_picker_navigation_wraps(speller):
    p = Picker(speller, limit=4, initial="recieve")
    first = p.current
    p.move(1)
    assert p.current == p.items[1].word
    p.move(-1); p.move(-1)
    assert p.current == p.items[-1].word
    p.move(1)
    assert p.current == first


def test_tab_accepts_into_input(speller):
    p = Picker(speller, limit=4, initial="seperat")
    p.move(0)
    chosen = p.current
    p.accept_into_input()
    assert p.buffer.text == chosen
    assert p.items[0].exact and p.selected == 0


def test_typing_resets_selection(speller):
    p = Picker(speller, limit=4, initial="recieve")
    p.move(2)
    p.buffer.insert_text("d")
    assert p.selected == 0
