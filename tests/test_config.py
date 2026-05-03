import json

import pytest

from cellos.config import ConfigError, ensure_config, load_agent_catalog, load_config, load_prompt_profiles


VALID_CONFIG = (
    '{"scheduler": {"concurrent_tasks": 2, "worker_timeout_seconds": 60}, '
    '"worker": {"backend": "acp", "debug_log_path": ".cellos/logs/acp-debug.log"}, '
    '"agents": {"default": "fake", "catalog_path": "agentcatalog.json"}, '
    '"prompts": {"profiles_path": "promptprofiles.json"}}'
)

VALID_AGENT_CATALOG = (
    '{"available": {'
    '"fake": {"connector": "fake_acp", "description": "Fake development agent"}, '
    '"opencode": {"connector": "opencode", "description": "OpenCode local ACP agent"}'
    "}}"
)

VALID_PROMPT_PROFILES = (
    '{"role_instructions": {"engineer": "Engineer instructions."}, '
    '"modes": {"planning": {"instructions": ["Mode: planning"], "output_sections": ["Objective"]}}, '
    '"final_instructions": ["Report concisely."]}'
)


def test_ensure_config_copies_example_when_missing(tmp_path):
    example = tmp_path / "example.json"
    catalog_example = tmp_path / "agentcatalog.example.json"
    profiles_example = tmp_path / "promptprofiles.example.json"
    config = tmp_path / ".cellos" / "config.json"
    catalog = tmp_path / ".cellos" / "agentcatalog.json"
    profiles = tmp_path / ".cellos" / "promptprofiles.json"
    example.write_text(VALID_CONFIG)
    catalog_example.write_text(VALID_AGENT_CATALOG)
    profiles_example.write_text(VALID_PROMPT_PROFILES)

    written = ensure_config(
        config,
        example,
        agent_catalog_path=catalog,
        agent_catalog_example_path=catalog_example,
        prompt_profiles_path=profiles,
        prompt_profiles_example_path=profiles_example,
    )
    loaded = load_config(written)

    assert written == config
    assert catalog.exists()
    assert profiles.exists()
    assert loaded.scheduler.concurrent_tasks == 2
    assert loaded.scheduler.worker_timeout_seconds == 60
    assert loaded.worker.backend == "acp"
    assert loaded.agents.default == "fake"
    assert loaded.agent_catalog.available["opencode"].connector == "opencode"
    assert loaded.prompt_profiles.role_instructions["engineer"] == "Engineer instructions."


def test_ensure_config_does_not_overwrite_existing_without_flag(tmp_path):
    example = tmp_path / "example.json"
    catalog_example = tmp_path / "agentcatalog.example.json"
    profiles_example = tmp_path / "promptprofiles.example.json"
    config = tmp_path / ".cellos" / "config.json"
    catalog = tmp_path / ".cellos" / "agentcatalog.json"
    profiles = tmp_path / ".cellos" / "promptprofiles.json"
    example.write_text(VALID_CONFIG)
    catalog_example.write_text(VALID_AGENT_CATALOG)
    profiles_example.write_text(VALID_PROMPT_PROFILES)
    config.parent.mkdir()
    config.write_text(
        '{"scheduler": {"concurrent_tasks": 7, "worker_timeout_seconds": 90}, '
        '"worker": {"backend": "acp", "debug_log_path": ".cellos/logs/acp-debug.log"}, '
        '"agents": {"default": "fake", "catalog_path": "agentcatalog.json"}}'
    )
    catalog.write_text('{"available": {"fake": {"connector": "fake_acp"}}}')
    profiles.write_text('{"role_instructions": {"engineer": "Original."}}')

    ensure_config(
        config,
        example,
        agent_catalog_path=catalog,
        agent_catalog_example_path=catalog_example,
        prompt_profiles_path=profiles,
        prompt_profiles_example_path=profiles_example,
    )
    loaded = load_config(config)

    assert loaded.scheduler.concurrent_tasks == 7
    assert list(loaded.agent_catalog.available) == ["fake"]
    assert loaded.prompt_profiles.role_instructions["engineer"] == "Original."


def test_ensure_config_overwrites_existing_with_flag(tmp_path):
    example = tmp_path / "example.json"
    catalog_example = tmp_path / "agentcatalog.example.json"
    profiles_example = tmp_path / "promptprofiles.example.json"
    config = tmp_path / ".cellos" / "config.json"
    catalog = tmp_path / ".cellos" / "agentcatalog.json"
    profiles = tmp_path / ".cellos" / "promptprofiles.json"
    example.write_text(VALID_CONFIG)
    catalog_example.write_text(VALID_AGENT_CATALOG)
    profiles_example.write_text(VALID_PROMPT_PROFILES)
    config.parent.mkdir()
    config.write_text(
        '{"scheduler": {"concurrent_tasks": 7, "worker_timeout_seconds": 90}, '
        '"worker": {"backend": "acp", "debug_log_path": ".cellos/logs/acp-debug.log"}, '
        '"agents": {"default": "fake", "catalog_path": "agentcatalog.json"}}'
    )
    catalog.write_text('{"available": {"fake": {"connector": "fake_acp"}}}')
    profiles.write_text('{"role_instructions": {"engineer": "Original."}}')

    ensure_config(
        config,
        example,
        agent_catalog_path=catalog,
        agent_catalog_example_path=catalog_example,
        prompt_profiles_path=profiles,
        prompt_profiles_example_path=profiles_example,
        overwrite=True,
    )
    loaded = load_config(config)

    assert loaded.scheduler.concurrent_tasks == 2
    assert "opencode" in loaded.agent_catalog.available
    assert loaded.prompt_profiles.role_instructions["engineer"] == "Engineer instructions."


def test_load_config_reports_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="Missing config file"):
        load_config(tmp_path / "missing.json")


def test_load_config_reports_invalid_json(tmp_path):
    config = tmp_path / "config.json"
    config.write_text("{not json")

    with pytest.raises(ConfigError, match="Invalid JSON"):
        load_config(config)


def test_load_config_reports_missing_agent_catalog(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(VALID_CONFIG)

    with pytest.raises(ConfigError, match="Missing agent catalog file"):
        load_config(config)


def test_load_config_reports_missing_prompt_profiles(tmp_path):
    config = tmp_path / "config.json"
    catalog = tmp_path / "agentcatalog.json"
    config.write_text(VALID_CONFIG)
    catalog.write_text(VALID_AGENT_CATALOG)

    with pytest.raises(ConfigError, match="Missing prompt profiles file"):
        load_config(config)


def test_load_agent_catalog_reports_invalid_json(tmp_path):
    catalog = tmp_path / "agentcatalog.json"
    catalog.write_text("{not json")

    with pytest.raises(ConfigError, match="Invalid JSON"):
        load_agent_catalog(catalog)


def test_load_prompt_profiles_reports_invalid_json(tmp_path):
    profiles = tmp_path / "promptprofiles.json"
    profiles.write_text("{not json")

    with pytest.raises(ConfigError, match="Invalid JSON"):
        load_prompt_profiles(profiles)


def test_agent_catalog_reports_missing_default_when_used(tmp_path):
    config = tmp_path / "config.json"
    catalog = tmp_path / "agentcatalog.json"
    profiles = tmp_path / "promptprofiles.json"
    config.write_text(VALID_CONFIG.replace('"default": "fake"', '"default": "missing"'))
    catalog.write_text(json.dumps({"available": {"fake": {"connector": "fake_acp"}}}))
    profiles.write_text(VALID_PROMPT_PROFILES)

    loaded = load_config(config)

    with pytest.raises(ValueError, match="Default agent"):
        loaded.get_default_agent()


def test_load_config_resolves_relative_agent_catalog_next_to_config(tmp_path):
    config = tmp_path / ".cellos" / "config.json"
    catalog = tmp_path / ".cellos" / "custom-agentcatalog.json"
    profiles = tmp_path / ".cellos" / "promptprofiles.json"
    config.parent.mkdir()
    config.write_text(
        '{"scheduler": {"concurrent_tasks": 2, "worker_timeout_seconds": 60}, '
        '"worker": {"backend": "acp"}, '
        '"agents": {"default": "fake", "catalog_path": "custom-agentcatalog.json"}}'
    )
    catalog.write_text(VALID_AGENT_CATALOG)
    profiles.write_text(VALID_PROMPT_PROFILES)

    loaded = load_config(config)

    assert loaded.get_default_agent().connector == "fake_acp"


def test_load_config_resolves_relative_prompt_profiles_next_to_config(tmp_path):
    config = tmp_path / ".cellos" / "config.json"
    catalog = tmp_path / ".cellos" / "agentcatalog.json"
    profiles = tmp_path / ".cellos" / "custom-promptprofiles.json"
    config.parent.mkdir()
    config.write_text(
        '{"scheduler": {"concurrent_tasks": 2, "worker_timeout_seconds": 60}, '
        '"worker": {"backend": "acp"}, '
        '"agents": {"default": "fake", "catalog_path": "agentcatalog.json"}, '
        '"prompts": {"profiles_path": "custom-promptprofiles.json"}}'
    )
    catalog.write_text(VALID_AGENT_CATALOG)
    profiles.write_text(VALID_PROMPT_PROFILES)

    loaded = load_config(config)

    assert loaded.prompt_profiles.modes["planning"].output_sections == ["Objective"]
