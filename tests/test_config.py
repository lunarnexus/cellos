"""Tests for configuration loading, validation, and defaults."""

import json
from pathlib import Path

import pytest

from cellos.config import (
    CellosConfig,
    ConfigError,
    SchedulerConfig,
    WorkerConfig,
    AgentCatalogEntry,
    PromptProfilesConfig,
    ModeProfile,
    ApprovalConfig,
    load_config,
    ensure_config,
)


class TestSchedulerConfig:
    def test_defaults(self):
        cfg = SchedulerConfig()
        assert cfg.concurrent_tasks == 4
        assert cfg.heartbeat_interval_seconds == 5.0

    def test_custom_values(self):
        cfg = SchedulerConfig(concurrent_tasks=8, heartbeat_interval_seconds=2.0)
        assert cfg.concurrent_tasks == 8
        assert cfg.heartbeat_interval_seconds == 2.0


class TestWorkerConfig:
    def test_defaults(self):
        cfg = WorkerConfig()
        assert cfg.backend == "acp"
        assert cfg.timeout_seconds == 300

    def test_custom_values(self):
        cfg = WorkerConfig(backend="local", timeout_seconds=600)
        assert cfg.backend == "local"
        assert cfg.timeout_seconds == 600


class TestAgentCatalogEntry:
    def test_minimal(self):
        entry = AgentCatalogEntry(connector="fake_acp")
        assert entry.connector == "fake_acp"
        assert entry.model is None
        assert entry.options == {}

    def test_with_model_and_options(self):
        entry = AgentCatalogEntry(
            connector="opencode", model="qwen-2.5-7b-instruct", options={"timeout": 60}
        )
        assert entry.connector == "opencode"
        assert entry.model == "qwen-2.5-7b-instruct"
        assert entry.options["timeout"] == 60


class TestCellosConfig:
    def test_full_defaults(self):
        cfg = CellosConfig()
        assert cfg.scheduler.concurrent_tasks == 4
        assert cfg.worker.backend == "acp"
        assert cfg.agents.default_agent_id == "engineer"
        assert cfg.approvals.preapprove_research_tasks is False
        assert cfg.agent_catalog == {}

    def test_get_agent_default(self):
        cfg = CellosConfig(
            agent_catalog={
                "engineer": AgentCatalogEntry(connector="fake_acp"),
                "architect": AgentCatalogEntry(connector="opencode", model="qwen-2.5-7b-instruct"),
            }
        )
        agent = cfg.get_agent()
        assert agent is not None
        assert agent.connector == "fake_acp"

    def test_get_agent_explicit(self):
        cfg = CellosConfig(
            agent_catalog={
                "engineer": AgentCatalogEntry(connector="fake_acp"),
                "architect": AgentCatalogEntry(connector="opencode", model="qwen-2.5-7b-instruct"),
            }
        )
        agent = cfg.get_agent("architect")
        assert agent is not None
        assert agent.connector == "opencode"

    def test_get_agent_missing(self):
        cfg = CellosConfig(agent_catalog={"engineer": AgentCatalogEntry(connector="fake_acp")})
        assert cfg.get_agent("nonexistent") is None


class TestLoadConfig:
    def test_load_from_temp_dir(self, tmp_path):
        """Full three-file config loads and resolves correctly."""
        (tmp_path / "config.json").write_text(json.dumps({
            "scheduler": {"concurrent_tasks": 8},
            "worker": {"backend": "acp", "timeout_seconds": 600},
            "agents": {"default_agent_id": "architect"},
            "approvals": {"preapprove_research_tasks": True},
        }))
        (tmp_path / "agentcatalog.json").write_text(json.dumps({
            "engineer": {"connector": "fake_acp", "options": {}},
            "architect": {"connector": "opencode", "model": "qwen-2.5-7b-instruct"},
        }))
        (tmp_path / "promptprofiles.json").write_text(json.dumps({
            "role_instructions": {"engineer": "You are an engineer."},
            "modes": {
                "planning": {"instructions": "Plan the task.", "output_sections": ["Steps"]},
            },
            "final_instructions": "",
        }))

        cfg = load_config(str(tmp_path))
        assert cfg.scheduler.concurrent_tasks == 8
        assert cfg.worker.timeout_seconds == 600
        assert cfg.agents.default_agent_id == "architect"
        assert cfg.approvals.preapprove_research_tasks is True
        assert len(cfg.agent_catalog) == 2
        assert cfg.get_agent().connector == "opencode"

    def test_load_missing_config_raises(self, tmp_path):
        with pytest.raises(ConfigError, match="Config file not found"):
            load_config(str(tmp_path))

    def test_load_invalid_json_raises(self, tmp_path):
        (tmp_path / "config.json").write_text("{invalid json}")
        with pytest.raises(ConfigError, match="Invalid JSON"):
            load_config(str(tmp_path))

    def test_load_without_catalog_or_profiles(self, tmp_path):
        """Catalog and profiles are optional — defaults used if missing."""
        (tmp_path / "config.json").write_text(json.dumps({}))
        cfg = load_config(str(tmp_path))
        assert isinstance(cfg.scheduler, SchedulerConfig)
        assert cfg.agent_catalog == {}

    def test_load_custom_catalog_path(self, tmp_path):
        """catalog_path in config resolves relative to config dir."""
        subdir = tmp_path / "agents"
        subdir.mkdir()
        (subdir / "my_agents.json").write_text(json.dumps({
            "test_agent": {"connector": "fake_acp"},
        }))
        (tmp_path / "config.json").write_text(json.dumps({
            "agents": {
                "default_agent_id": "test_agent",
                "catalog_path": "agents/my_agents.json",
            },
        }))

        cfg = load_config(str(tmp_path))
        assert len(cfg.agent_catalog) == 1
        assert "test_agent" in cfg.agent_catalog

    def test_example_env_includes_vikunja_variables(self):
        env_example = Path(__file__).resolve().parents[1] / "cellos" / "env.example"
        content = env_example.read_text()

        assert "VIKUNJA_BASE_URL=" in content
        assert "VIKUNJA_API_TOKEN=" in content

    def test_example_config_mentions_vikunja_provider_shape(self):
        config_example = Path(__file__).resolve().parents[1] / "cellos" / "cellos.config.json.example"
        data = json.loads(config_example.read_text())

        assert "vikunja" in data["integrations"]["providers"]
        assert data["integrations"]["providers"]["vikunja"]["project_id"]
        assert data["integrations"]["providers"]["vikunja"]["view_id"]
        assert data["integrations"]["providers"]["vikunja"]["bucket_map"]


class TestEnsureConfig:
    def test_creates_files(self, tmp_path):
        result = ensure_config(str(tmp_path / "config"))
        assert (result / "config.json").exists()
        assert (result / "agentcatalog.json").exists()
        assert (result / "promptprofiles.json").exists()

    def test_skips_existing_without_overwrite(self, tmp_path):
        dest = tmp_path / "cfg"
        ensure_config(str(dest))
        original_mtime = (dest / "config.json").stat().st_mtime
        import time; time.sleep(0.05)
        ensure_config(str(dest), overwrite=False)
        assert (dest / "config.json").stat().st_mtime == original_mtime

    def test_overwrites_existing(self, tmp_path):
        dest = tmp_path / "cfg"
        ensure_config(str(dest))
        (dest / "config.json").write_text("old")
        import time; time.sleep(0.05)
        ensure_config(str(dest), overwrite=True)
        data = json.loads((dest / "config.json").read_text())
        assert "scheduler" in data

    def test_creates_parent_dirs(self, tmp_path):
        result = ensure_config(str(tmp_path / "a" / "b" / "c"))
        assert (result / "config.json").exists()


class TestPromptProfilesConfig:
    def test_mode_profile_defaults(self):
        mp = ModeProfile(instructions="Do the thing.")
        assert mp.instructions == "Do the thing."
        assert mp.output_sections == []

    def test_prompt_profiles_empty(self):
        cfg = PromptProfilesConfig()
        assert cfg.role_instructions == {}
        assert cfg.modes == {}
        assert cfg.final_instructions == ""





class TestProviderConfigBoardId:
    """Test provider config extra fields and writer helper."""

    def test_provider_config_extra_field_default_missing(self):
        from cellos.config import ProviderConfig
        tc = ProviderConfig()
        assert getattr(tc, "board_id", None) is None

    def test_provider_config_set_extra_field(self):
        from cellos.config import ProviderConfig
        tc = ProviderConfig(board_id="abc123")
        assert tc.board_id == "abc123"

    def test_provider_config_extra_field(self):
        from cellos.config import ProviderConfig
        pc = ProviderConfig(board_id="abc123")
        assert pc.board_id == "abc123"

    def test_load_config_with_provider_block(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({
            "integrations": {
                "wekan": {
                    "auto_sync_enabled": True,
                    "board_id": "test-board-123"
                }
            }
        }))
        cfg = load_config(str(tmp_path))
        assert cfg.integrations.wekan.board_id == "test-board-123"

    def test_load_config_with_vikunja_provider_block(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({
            "integrations": {
                "vikunja": {
                    "auto_sync_enabled": True,
                    "project_id": "project-7",
                    "view_id": "view-2",
                    "bucket_map": {"backlog": "11", "done": "22"}
                }
            }
        }))
        cfg = load_config(str(tmp_path))
        assert cfg.integrations.vikunja.project_id == "project-7"
        assert cfg.integrations.vikunja.view_id == "view-2"
        assert cfg.integrations.vikunja.bucket_map == {"backlog": "11", "done": "22"}
