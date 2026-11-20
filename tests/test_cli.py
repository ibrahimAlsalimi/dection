import subprocess
import sys

import pytest

from spell import cli, clipboard, dictionary


def run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def test_single_word_correction(capsys):
    code, out, err = run(capsys, "recieve")
    assert (code, out, err) == (0, "receive\n", "")


def test_correct_word_is_echoed(capsys):
    assert run(capsys, "receive") == (0, "receive\n", "")


def test_unknown_word(capsys):
    code, out, err = run(capsys, "xqzvwk")
    assert code == cli.EXIT_NO_MATCH and out == "" and "no suggestions" in err


def test_nonalphabetic_word(capsys):
    code, out, _ = run(capsys, "1234")
    assert code == cli.EXIT_NO_MATCH and out == ""


def test_suggest_lists_one_per_line(capsys):
    code, out, err = run(capsys, "--suggest", "recieve")
    lines = out.splitlines()
    assert code == 0 and err == ""
    assert lines[0] == "receive" and 1 < len(lines) <= 8
    assert all(line.strip() == line and " " not in line for line in lines)


def test_suggest_limit(capsys):
    code, out, _ = run(capsys, "--suggest", "--limit", "3", "recieve")
    assert code == 0 and len(out.splitlines()) == 3


@pytest.mark.parametrize("args", [["--limit", "0", "x"], ["--limit", "abc", "x"], ["--suggest"]])
def test_usage_errors(capsys, args):
    with pytest.raises(SystemExit) as e:
        cli.main(args)
    assert e.value.code == 2
    assert capsys.readouterr().out == ""


def test_help(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--suggest" in out and "--copy" in out and "--limit" in out


def test_missing_dictionary(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(dictionary, "bundled_path", lambda: tmp_path / "missing.tsv")
    code, out, err = run(capsys, "recieve")
    assert code == cli.EXIT_ERROR and out == "" and "not found" in err


def test_user_words_via_env(capsys, monkeypatch, tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("Kubernetes\n")
    monkeypatch.setenv("SPELL_USER_WORDS", str(f))
    assert run(capsys, "kubernets") == (0, "Kubernetes\n", "")
    code, out, _ = run(capsys, "--no-user-words", "kubernets")
    assert out != "Kubernetes\n"


def test_copy_success(capsys, monkeypatch):
    copied = []
    monkeypatch.setattr(clipboard, "copy", lambda w: copied.append(w) or "fake")
    assert run(capsys, "--copy", "recieve") == (0, "receive\n", "")
    assert copied == ["receive"]


def test_copy_failure_keeps_word(capsys, monkeypatch):
    def fail(_):
        raise clipboard.ClipboardError("no clipboard tool")
    monkeypatch.setattr(clipboard, "copy", fail)
    code, out, err = run(capsys, "--copy", "recieve")
    assert code == cli.EXIT_CLIPBOARD and out == "receive\n" and "no clipboard tool" in err


def test_clipboard_without_display(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(clipboard.ClipboardError):
        clipboard.copy("x")


def test_interactive_without_terminal_fails_cleanly(capsys, monkeypatch):
    from spell import tui

    def no_tty(*a, **k):
        raise tui.NoTerminalError("interactive mode needs a terminal")
    monkeypatch.setattr(tui, "run", no_tty)
    code, out, err = run(capsys)
    assert code == cli.EXIT_ERROR and out == "" and "terminal" in err


def test_subprocess_stdout_is_clean(tmp_path):
    env = {"XDG_CACHE_HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, "-m", "spell", "Definately"], capture_output=True,
                       text=True, env=env, timeout=60)
    assert (r.returncode, r.stdout, r.stderr) == (0, "Definitely\n", "")
    r = subprocess.run([sys.executable, "-m", "spell", "qqqqqq"], capture_output=True,
                       text=True, env=env, timeout=60)
    assert r.returncode == 1 and r.stdout == ""
