"""fzf-style interactive picker built on prompt_toolkit.

The UI is drawn on the controlling terminal (/dev/tty), never on stdout, so
``word=$(spell)`` captures only the selected word.
"""

from __future__ import annotations

import os
import sys
from contextlib import ExitStack

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.input import create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.output import create_output
from prompt_toolkit.styles import Style

from .engine import Speller
from .ranking import Suggestion

STYLE = Style.from_dict({
    "header": "bold",
    "prompt": "ansicyan bold",
    "pointer": "ansired bold",
    "selected": "reverse",
    "dim": "ansibrightblack",
    "ok": "ansigreen",
})


class NoTerminalError(Exception):
    pass


class Picker:
    def __init__(self, speller: Speller, limit: int, initial: str = ""):
        self.speller = speller
        self.limit = limit
        self.items: list[Suggestion] = []
        self.selected = 0
        self.buffer = Buffer(multiline=False, on_text_changed=self._refresh)
        self.buffer.text = initial
        self.buffer.cursor_position = len(initial)
        self._refresh()

    def _refresh(self, _buf: Buffer | None = None) -> None:
        self.items = self.speller.suggest(self.buffer.text, self.limit)
        self.selected = 0

    def move(self, delta: int) -> None:
        if self.items:
            self.selected = (self.selected + delta) % len(self.items)

    @property
    def current(self) -> str | None:
        return self.items[self.selected].word if self.items else None

    def accept_into_input(self) -> None:
        if self.current is not None:
            self.buffer.text = self.current  # triggers _refresh
            self.buffer.cursor_position = len(self.buffer.text)

    def _status(self):
        text = self.buffer.text.strip()
        if not text:
            return [("class:dim", "  type a word")]
        if not self.items:
            return [("class:dim", "  no suggestions")]
        if self.items[0].exact:
            return [("class:ok", "  ✓ spelled correctly")]
        n = len(self.items)
        return [("class:dim", f"  {n} suggestion{'s' if n != 1 else ''}")]

    def _list(self):
        out = []
        for i, s in enumerate(self.items):
            if i == self.selected:
                out += [("class:pointer", "  > "), ("class:selected", s.word)]
            else:
                out += [("", "    " + s.word)]
            out.append(("", "\n"))
        return out

    def application(self, **io) -> Application[str | None]:
        kb = KeyBindings()

        @kb.add("up")
        @kb.add("c-p")
        def _(event):
            self.move(-1)

        @kb.add("down")
        @kb.add("c-n")
        def _(event):
            self.move(1)

        @kb.add("enter")
        def _(event):
            if self.current is not None:
                event.app.exit(result=self.current)

        @kb.add("escape", eager=True)
        @kb.add("c-c")
        @kb.add("c-g")
        def _(event):
            event.app.exit(result=None)

        @kb.add("c-u")
        def _(event):
            self.buffer.reset()
            self._refresh()

        @kb.add("tab")
        def _(event):
            self.accept_into_input()

        layout = Layout(HSplit([
            Window(FormattedTextControl([("class:header", "  spell - English Spelling Correction")]), height=1),
            VSplit([
                Window(FormattedTextControl([("class:prompt", "  > ")]), width=4, height=1),
                Window(BufferControl(self.buffer), height=1),
            ]),
            Window(FormattedTextControl(self._status), height=1),
            Window(FormattedTextControl(self._list), height=self.limit),
            Window(FormattedTextControl([("class:dim", "  ↑↓ Navigate | Enter Select | Tab Complete | Esc Exit")]), height=1),
        ]))
        app: Application[str | None] = Application(
            layout=layout, key_bindings=kb, style=STYLE, full_screen=False,
            erase_when_done=True, mouse_support=False, **io)
        app.ttimeoutlen = 0.05
        app.timeoutlen = 0.05
        return app


def run(speller: Speller, limit: int, initial: str = "") -> str | None:
    """Run the picker; return the chosen word, or None if cancelled."""
    with ExitStack() as stack:
        try:
            tty = stack.enter_context(open("/dev/tty", "r+", encoding="utf-8"))
            tty_in = tty_out = tty
        except OSError:
            if not (sys.stdin.isatty() and sys.stderr.isatty()):
                raise NoTerminalError("interactive mode needs a terminal") from None
            tty_in, tty_out = sys.stdin, sys.stderr
        if not os.isatty(tty_out.fileno()):
            raise NoTerminalError("interactive mode needs a terminal")
        picker = Picker(speller, limit, initial)
        app = picker.application(input=create_input(tty_in), output=create_output(stdout=tty_out))
        try:
            return app.run()
        except (KeyboardInterrupt, EOFError):
            return None
