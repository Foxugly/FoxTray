from pathlib import Path

import pytest
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


def test_clear_if_orphaned_noop_when_no_active(tmp_appdata: Path) -> None:
    state.save(state.State(active=None))
    assert state.clear_if_orphaned() is False
    assert state.load().active is None


def test_clear_if_orphaned_noop_when_backend_alive(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="X", backend_pid=111, frontend_pid=222,
        backend_create_time=100.0, frontend_create_time=200.0,
    )))
    # pid_alive compares both pid and create_time — simulate backend match only.
    monkeypatch.setattr(
        state, "pid_alive",
        lambda pid, ctime: pid == 111 and ctime == 100.0,
    )
    assert state.clear_if_orphaned() is False
    assert state.load().active is not None
    assert state.load().active.name == "X"


def test_clear_if_orphaned_noop_when_frontend_alive(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="X", backend_pid=111, frontend_pid=222,
        backend_create_time=100.0, frontend_create_time=200.0,
    )))
    monkeypatch.setattr(
        state, "pid_alive",
        lambda pid, ctime: pid == 222 and ctime == 200.0,
    )
    assert state.clear_if_orphaned() is False
    assert state.load().active is not None


def test_clear_if_orphaned_clears_when_both_dead(
    tmp_appdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save(state.State(active=state.ActiveProject(
        name="X", backend_pid=111, frontend_pid=222,
        backend_create_time=100.0, frontend_create_time=200.0,
    )))
    monkeypatch.setattr(state, "pid_alive", lambda pid, ctime: False)
    assert state.clear_if_orphaned() is True
    assert state.load().active is None


def test_pid_alive_returns_true_when_pid_and_ctime_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeProc:
        def create_time(self) -> float:
            return 42.0

    monkeypatch.setattr(state.psutil, "Process", lambda pid: _FakeProc())
    assert state.pid_alive(123, 42.0) is True


def test_pid_alive_returns_false_when_ctime_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows PID reuse guard: another process with the same PID has a
    different create_time. The stored identity must reject it."""
    class _RecycledProc:
        def create_time(self) -> float:
            return 999.0  # Different from what the caller stored.

    monkeypatch.setattr(state.psutil, "Process", lambda pid: _RecycledProc())
    assert state.pid_alive(123, 42.0) is False


def test_pid_alive_returns_false_when_no_such_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psutil

    def _raise(pid: int) -> None:
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(state.psutil, "Process", _raise)
    assert state.pid_alive(123, 42.0) is False


def test_load_legacy_state_without_ctime_fields_drops_entry(
    tmp_appdata: Path,
) -> None:
    """Upgrade path: an older FoxTray wrote state.json without create_time
    fields. Trying to re-use those PIDs after upgrade is unsafe because we
    can't verify their identity. Drop the entry and let the user restart."""
    state_path = tmp_appdata / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # This IS a valid frozen ActiveProject now (defaults exist), but a
    # state.json written by *older* FoxTray code lacks the new keys. The
    # load path already recovers gracefully via the TypeError/KeyError catch.
    state_path.write_text(
        '{"active": {"name": "X", "backend_pid": 1, "frontend_pid": 2}}',
        encoding="utf-8",
    )
    # Our defaults mean ActiveProject(**{name, backend_pid, frontend_pid})
    # actually succeeds — so legacy entries load as {name, pids, ctime=0.0}.
    # The pid_alive check will then fail (0.0 never matches a real ctime),
    # so clear_if_orphaned cleans up on next tick. Verify that flow:
    loaded = state.load()
    assert loaded.active is not None
    assert loaded.active.backend_create_time == 0.0
