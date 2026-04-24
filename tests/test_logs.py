from pathlib import Path

from foxtray import logs, paths


def test_rotate_with_no_existing_log_is_noop(tmp_appdata: Path) -> None:
    logs.rotate("FoxRunner", "backend")
    assert not paths.log_file("FoxRunner", "backend").exists()


def test_rotate_moves_current_to_dot_one(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    current = paths.log_file("FoxRunner", "backend")
    current.write_text("run A", encoding="utf-8")
    logs.rotate("FoxRunner", "backend")
    assert not current.exists()
    assert (current.parent / "FoxRunner_backend.log.1").read_text(encoding="utf-8") == "run A"


def test_rotate_overwrites_existing_dot_one(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    current = paths.log_file("FoxRunner", "backend")
    old = current.parent / "FoxRunner_backend.log.1"
    old.write_text("run OLD", encoding="utf-8")
    current.write_text("run NEW", encoding="utf-8")
    logs.rotate("FoxRunner", "backend")
    assert old.read_text(encoding="utf-8") == "run NEW"


def test_open_returns_write_handle(tmp_appdata: Path) -> None:
    handle = logs.open_writer("FoxRunner", "backend")
    try:
        handle.write("hello\n")
    finally:
        handle.close()
    assert paths.log_file("FoxRunner", "backend").read_text(encoding="utf-8") == "hello\n"


def test_tail_returns_last_n_lines(tmp_appdata: Path) -> None:
    paths.ensure_dirs()
    log_path = paths.log_file("FoxRunner", "backend")
    log_path.write_text("\n".join(f"line {i}" for i in range(10)) + "\n", encoding="utf-8")
    assert logs.tail("FoxRunner", "backend", lines=3) == ["line 7", "line 8", "line 9"]


def test_rotate_task_creates_tasks_subdir_and_sanitizes_key(tmp_appdata: Path) -> None:
    # No existing log file — rotate is a no-op but creates the dir
    logs.rotate_task("task:FoxRunner:Migrate")
    tasks_dir = paths.appdata_root() / "logs" / "tasks"
    assert tasks_dir.exists()


def test_open_task_writer_writes_to_sanitized_path(tmp_appdata: Path) -> None:
    fh = logs.open_task_writer("task:FoxRunner:Migrate")
    fh.write("hello task log\n")
    fh.close()
    expected = paths.appdata_root() / "logs" / "tasks" / "task_FoxRunner_Migrate.log"
    assert expected.exists()
    assert "hello task log" in expected.read_text(encoding="utf-8")


def test_rotate_task_moves_existing_log_to_dot1(tmp_appdata: Path) -> None:
    fh = logs.open_task_writer("script:Git pull all")
    fh.write("first run\n")
    fh.close()

    logs.rotate_task("script:Git pull all")

    rotated = paths.appdata_root() / "logs" / "tasks" / "script_Git pull all.log.1"
    assert rotated.exists()
    assert "first run" in rotated.read_text(encoding="utf-8")


def test_logs_dir_returns_appdata_logs(tmp_appdata: Path) -> None:
    assert paths.logs_dir() == paths.appdata_root() / "logs"


def test_rotate_with_keep_3_rotates_two_levels(tmp_appdata: Path) -> None:
    # Write some "current" content, rotate, repeat — verify X.log.1 and X.log.2
    first = logs.open_writer("X", "b")
    first.write("first\n")
    first.close()
    logs.rotate("X", "b", keep=3)
    second = logs.open_writer("X", "b")
    second.write("second\n")
    second.close()
    logs.rotate("X", "b", keep=3)
    third = logs.open_writer("X", "b")
    third.write("third\n")
    third.close()
    # Now X.log = "third", X.log.1 = "second", X.log.2 = "first"
    root = paths.appdata_root() / "logs"
    assert "first" in (root / "X_b.log.2").read_text(encoding="utf-8")
    assert "second" in (root / "X_b.log.1").read_text(encoding="utf-8")
    assert "third" in (root / "X_b.log").read_text(encoding="utf-8")


def test_rotate_with_keep_2_preserves_old_behavior(tmp_appdata: Path) -> None:
    first = logs.open_writer("X", "b")
    first.write("first\n")
    first.close()
    logs.rotate("X", "b", keep=2)
    second = logs.open_writer("X", "b")
    second.write("second\n")
    second.close()
    logs.rotate("X", "b", keep=2)
    # X.log.1 has "second", X.log.2 should NOT exist
    root = paths.appdata_root() / "logs"
    assert (root / "X_b.log.1").exists()
    assert "second" in (root / "X_b.log.1").read_text(encoding="utf-8")
    assert not (root / "X_b.log.2").exists()


def test_rotate_with_keep_1_is_noop(tmp_appdata: Path) -> None:
    fh = logs.open_writer("X", "b")
    fh.write("content\n")
    fh.close()
    logs.rotate("X", "b", keep=1)
    root = paths.appdata_root() / "logs"
    assert (root / "X_b.log").exists()
    assert not (root / "X_b.log.1").exists()
