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
