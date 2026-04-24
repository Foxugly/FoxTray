def test_version_is_string() -> None:
    from foxtray import __version__
    assert isinstance(__version__, str)
    assert len(__version__) > 0
