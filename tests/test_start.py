"""Program start: two starts at once must not crash."""
from __future__ import annotations

import os
import threading

import pytest

from metastat import paths, secure, store
from metastat.web import app as webapp


def test_ensure_dir_survives_parallel_creation(tmp_path):
    target = tmp_path / "data" / "logs"
    errors = []

    def make():
        try:
            paths.ensure_dir(target)
        except OSError as e:  # pragma: no cover - this is exactly what must not happen
            errors.append(e)

    threads = [threading.Thread(target=make) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and target.is_dir()


def test_data_folder_per_mode(tmp_path, monkeypatch):
    """From source: project\\data. Portable EXE (data next to it): there. Installed EXE: %LOCALAPPDATA%\\Metastat."""
    monkeypatch.delenv("METASTAT_DATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData"))
    app = tmp_path / "Program Files" / "Metastat"
    app.mkdir(parents=True)
    monkeypatch.setattr(paths, "app_dir", lambda: app)
    monkeypatch.setattr(paths, "frozen", lambda: False)
    assert paths.home() == app / "data"
    monkeypatch.setattr(paths, "frozen", lambda: True)
    assert paths.home() == tmp_path / "AppData" / "Metastat"      # installed
    (app / "data").mkdir()
    assert paths.home() == app / "data"                           # portable
    monkeypatch.setenv("METASTAT_DATA", str(tmp_path / "x"))
    assert paths.home() == (tmp_path / "x").resolve()


def test_ensure_dir_ignores_false_not_a_directory(tmp_path, monkeypatch):
    """Windows says "already exists" and the "is it a folder" check briefly lies (antivirus scan).
    Path.mkdir(exist_ok=True) then crashes (that happened in the EXE); ensure_dir must pass."""
    from pathlib import Path
    (tmp_path / "data" / "logs").mkdir(parents=True)
    monkeypatch.setattr(Path, "is_dir", lambda self, **kw: False)
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    with pytest.raises(FileExistsError):
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)   # the old way: the error from the screenshot
    assert paths.ensure_dir(tmp_path / "data") == tmp_path / "data"
    assert paths.ensure_dir(tmp_path / "data" / "logs" / "new").exists()
    assert paths.ensure_dir(tmp_path / "a" / "b" / "c").exists()   # parent folders are created too


def test_two_stores_first_run_at_once(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    home = tmp_path / "data"
    results, errors = [], []

    def run():
        try:
            results.append(store.Store(home).load())
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=run) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(results) == 8 and (home / "metastat.json").is_file()


def test_first_write_keeps_the_winner(tmp_path, monkeypatch):
    """Two processes on the first start: the late one does not overwrite the file, it loads the saved one."""
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)
    home = tmp_path / "data"
    winner = store.Store(home).load()
    late = store.Store(home)
    assert late._write({"version": 1, "settings": {}, "connections": [{"id": "x"}], "active": "x"}, create=True) is False
    assert store.Store(home).load()["connections"] == winner["connections"]
    assert not list(home.glob(".metastat-*.json"))   # no leftovers after the late write


def test_second_start_opens_running_window(tmp_path, monkeypatch):
    """A second start does not bring up a second server: it reads the encrypted address and opens the window."""
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setattr(webapp, "_first_instance", lambda home: False)
    opened = []
    monkeypatch.setattr(webapp, "_open_window", lambda url, profile: opened.append(url))
    url = "http://127.0.0.1:5555/start?k=abc"
    (tmp_path / ".window-address").write_text(secure.encrypt(url), encoding="ascii")
    assert url not in (tmp_path / ".window-address").read_text(encoding="ascii")   # only the ciphertext on disk
    assert webapp.run_app() == 0 and opened == [url]


def test_mutex_detects_second_instance(tmp_path):
    assert webapp._first_instance(tmp_path) is True
    assert webapp._first_instance(tmp_path) is False   # the same data folder: already running
    assert webapp._first_instance(tmp_path / "other") is True
