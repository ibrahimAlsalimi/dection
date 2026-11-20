import pytest

from spell import dictionary
from spell.engine import Speller


@pytest.fixture(scope="session")
def cache_home(tmp_path_factory):
    return tmp_path_factory.mktemp("cache")


@pytest.fixture(scope="session")
def speller(cache_home):
    d = dictionary.load(use_user_words=False)
    return Speller(d, cache=cache_home / "spell")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path, cache_home):
    # never read the developer's real word list or write to their cache;
    # the index cache is shared between tests to keep the suite fast
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.delenv("SPELL_USER_WORDS", raising=False)
