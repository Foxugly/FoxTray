from pathlib import Path

from foxtray import state


def test_load_returns_empty_when_missing(tmp_appdata: Path) -> None:
    assert state.load() == state.State(active=None)


def test_save_then_load_roundtrip(tmp_appdata: Path) -> None:
    snapshot = state.State(active=state.ActiveProject(name="FoxRunner", backend_pid=1234, frontend_pid=5678))
    state.save(snapshot)
    assert state.load() == snapshot


def test_clear_removes_active(tmp_appdata: Path) -> None:
    state.save(state.State(active=state.ActiveProject(name="X", backend_pid=1, frontend_pid=2)))
    state.clear()
    assert state.load().active is None


def test_load_recovers_from_corrupt_file(tmp_appdata: Path) -> None:
    state_path = tmp_appdata / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not json", encoding="utf-8")
    assert state.load().active is None


def test_load_recovers_from_schema_mismatch(tmp_appdata: Path) -> None:
    state_path = tmp_appdata / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        '{"active": {"name": "X", "backend_pid": 1, "frontend_pid": 2, "stale_key": true}}',
        encoding="utf-8",
    )
    assert state.load().active is None
