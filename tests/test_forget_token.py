import stat

import pytest

from mapwright import cli, config, track


@pytest.fixture
def proj(mw_home, monkeypatch):
    root = mw_home / "proj"
    (root / ".git").mkdir(parents=True)
    (root / "app.py").write_text("def hello():\n    return 1\n")
    monkeypatch.chdir(root)
    config.reset_cache()
    track._PROJECTS.clear()
    yield root
    config.set_start(None)
    config.reset_cache()


def run(*argv):
    assert cli.main(list(argv)) == 0


def test_forget_unregisters_keeps_history(proj):
    run("init")
    key = track.open_project(str(proj)).key
    assert key in config.projects()
    run("forget")
    assert key not in config.projects()
    assert (config.home() / "projects" / key).is_dir()


def test_purge_deletes_only_project_history(proj):
    run("init")
    key = track.open_project(str(proj)).key
    other = config.home() / "projects" / "other-12345678"
    other.mkdir(parents=True)
    run("forget", "--purge", "--yes")
    assert not (config.home() / "projects" / key).exists()
    assert other.is_dir() and (proj / "app.py").exists()


def test_purge_asks_without_yes(proj):
    run("init")
    key = track.open_project(str(proj)).key
    run("forget", "--purge")  # stdin is not a tty: nothing is deleted
    assert (config.home() / "projects" / key).is_dir()


def test_local_home_purge(proj, monkeypatch):
    monkeypatch.delenv("MAPWRIGHT_HOME")
    run("init", "--local")
    assert (proj / ".mapwright" / "home.json").is_file()
    run("forget", "--purge", "--yes")
    assert not (proj / ".mapwright").exists()
    assert ".mapwright/" in (proj / ".gitignore").read_text().splitlines()
    assert (proj / "app.py").exists()


def test_token_rotate_changes_and_keeps_mode(mw_home, capsys):
    old = config.token()
    run("token", "--rotate")
    new = config.token()
    assert new and new != old
    assert stat.S_IMODE((config.home() / "token").stat().st_mode) == 0o600
    assert new not in capsys.readouterr().out


def test_token_never_printed_without_show(mw_home, capsys):
    tok = config.token()
    run("token")
    out = capsys.readouterr().out
    assert tok not in out and str(config.home() / "token") in out
    run("token", "--show")
    assert tok in capsys.readouterr().out
