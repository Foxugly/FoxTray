from pathlib import Path

import pytest

from foxtray import paths


def test_appdata_root_uses_env_override(tmp_appdata: Path) -> None:
    assert paths.appdata_root() == tmp_appdata


def test_logs_dir_is_under_appdata(tmp_appdata: Path) -> None:
    assert paths.logs_dir() == tmp_appdata / "logs"


def test_state_file_is_under_appdata(tmp_appdata: Path) -> None:
    assert paths.state_file() == tmp_appdata / "state.json"


def test_ensure_dirs_creates_logs_dir(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    assert (tmp_appdata / "logs").is_dir()


def test_log_file_path_format(tmp_appdata: Path) -> None:
    assert paths.log_file("FoxRunner", "backend") == tmp_appdata / "logs" / "FoxRunner_backend.log"


def test_appdata_root_ignores_empty_override(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FOXTRAY_APPDATA", "")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert paths.appdata_root() == tmp_path / "foxtray"


def test_bootstrap_log_file_uses_exe_dir_when_frozen(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_exe = tmp_path / "FoxTray.exe"
    fake_exe.write_bytes(b"")
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(fake_exe), raising=False)
    assert paths.bootstrap_log_file() == tmp_path / "bootstrap.log"


def test_bootstrap_log_candidates_frozen_include_fallbacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_exe = tmp_path / "FoxTray.exe"
    fake_exe.write_bytes(b"")
    appdata = tmp_path / "appdata"
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(fake_exe), raising=False)
    monkeypatch.setenv("APPDATA", str(appdata))
    candidates = paths.bootstrap_log_candidates()
    assert candidates[0] == tmp_path / "bootstrap.log"
    assert appdata / "foxtray" / "logs" / "bootstrap.log" in candidates
