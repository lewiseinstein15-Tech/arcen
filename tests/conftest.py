"""Suite-wide isolation: no test may read or write the developer's ~/.arcen.

Server tests build ``ServerState(config=ArcenConfig())``, whose session store
defaults to ``~/.arcen/sessions``. Without a redirect, running the suite writes
session files and seeded config into the real home directory. Each test gets a
private HOME; tests that need a specific layout still set HOME themselves.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    # Outside tmp_path: several tests assert tmp_path stays empty.
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ARCEN_CONFIG_PATH", raising=False)
    return home
