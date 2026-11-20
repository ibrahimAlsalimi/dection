"""Copy text to the system clipboard using whatever platform tool exists."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


class ClipboardError(Exception):
    pass


def _commands() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbcopy"]]
    if sys.platform.startswith("win"):
        return [["clip"]]
    cmds: list[list[str]] = []
    if os.environ.get("WAYLAND_DISPLAY"):
        cmds.append(["wl-copy"])
    if os.environ.get("DISPLAY"):
        cmds += [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    return cmds


def copy(text: str) -> str:
    """Copy ``text``; return the name of the tool used. Raises ClipboardError."""
    cmds = _commands()
    if not cmds:
        raise ClipboardError("no graphical session found (neither WAYLAND_DISPLAY nor DISPLAY is set)")
    tried = []
    for cmd in cmds:
        if shutil.which(cmd[0]) is None:
            tried.append(f"{cmd[0]} (not installed)")
            continue
        try:
            # The tools fork a background process that owns the clipboard; it
            # must not inherit our pipes, or we would wait for it forever.
            r = subprocess.run(cmd, input=text.encode("utf-8"), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.TimeoutExpired) as e:
            tried.append(f"{cmd[0]} ({e.__class__.__name__})")
            continue
        if r.returncode == 0:
            return cmd[0]
        tried.append(f"{cmd[0]} (exit {r.returncode})")
    hint = "install wl-clipboard (Wayland) or xclip/xsel (X11)"
    raise ClipboardError(f"could not copy to clipboard: tried {', '.join(tried)}; {hint}")
