import pytest

from cellos.config import ConfigError, ensure_config, load_config


def test_ensure_config_copies_example_when_missing(tmp_path):
    example = tmp_path / "example.json"
    config = tmp_path / ".cellos" / "config.json"
    example.write_text(
        '{"scheduler": {"concurrent_tasks": 2, "worker_timeout_seconds": 60}, '
        '"worker": {"backend": "acp", "command": ["python3", "tests/fakes/acp_server.py"], '
        '"debug_log_path": ".cellos/acp-debug.log"}}'
    )

    written = ensure_config(config, example)
    loaded = load_config(written)

    assert written == config
    assert loaded.scheduler.concurrent_tasks == 2
    assert loaded.scheduler.worker_timeout_seconds == 60
    assert loaded.worker.backend == "acp"


def test_ensure_config_does_not_overwrite_existing_without_flag(tmp_path):
    example = tmp_path / "example.json"
    config = tmp_path / ".cellos" / "config.json"
    example.write_text(
        '{"scheduler": {"concurrent_tasks": 2, "worker_timeout_seconds": 60}, '
        '"worker": {"backend": "acp", "command": ["python3", "tests/fakes/acp_server.py"], '
        '"debug_log_path": ".cellos/acp-debug.log"}}'
    )
    config.parent.mkdir()
    config.write_text(
        '{"scheduler": {"concurrent_tasks": 7, "worker_timeout_seconds": 90}, '
        '"worker": {"backend": "acp", "command": ["python3", "tests/fakes/acp_server.py"], '
        '"debug_log_path": ".cellos/acp-debug.log"}}'
    )

    ensure_config(config, example)
    loaded = load_config(config)

    assert loaded.scheduler.concurrent_tasks == 7


def test_ensure_config_overwrites_existing_with_flag(tmp_path):
    example = tmp_path / "example.json"
    config = tmp_path / ".cellos" / "config.json"
    example.write_text(
        '{"scheduler": {"concurrent_tasks": 2, "worker_timeout_seconds": 60}, '
        '"worker": {"backend": "acp", "command": ["python3", "tests/fakes/acp_server.py"], '
        '"debug_log_path": ".cellos/acp-debug.log"}}'
    )
    config.parent.mkdir()
    config.write_text(
        '{"scheduler": {"concurrent_tasks": 7, "worker_timeout_seconds": 90}, '
        '"worker": {"backend": "acp", "command": ["python3", "tests/fakes/acp_server.py"], '
        '"debug_log_path": ".cellos/acp-debug.log"}}'
    )

    ensure_config(config, example, overwrite=True)
    loaded = load_config(config)

    assert loaded.scheduler.concurrent_tasks == 2


def test_load_config_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Missing config file"):
        load_config(tmp_path / "missing.json")


def test_load_config_reports_invalid_json(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{not json")

    with pytest.raises(ConfigError, match="Invalid JSON"):
        load_config(config)
