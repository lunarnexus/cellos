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
            connector="cellos_acp", model="qwen-2.5-7b-instruct", options={"timeout": 60}
        )
        assert entry.connector == "cellos_acp"
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
                "architect": AgentCatalogEntry(connector="cellos_acp", model="qwen-2.5-7b-instruct"),
            }
        )
        agent = cfg.get_agent()
        assert agent is not None
        assert agent.connector == "fake_acp"

    def test_get_agent_explicit(self):
        cfg = CellosConfig(
            agent_catalog={
                "engineer": AgentCatalogEntry(connector="fake_acp"),
                "architect": AgentCatalogEntry(connector="cellos_acp", model="qwen-2.5-7b-instruct"),
            }
        )
        agent = cfg.get_agent("architect")
        assert agent is not None
        assert agent.connector == "cellos_acp"

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
            "architect": {"connector": "cellos_acp", "model": "qwen-2.5-7b-instruct"},
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
        assert cfg.get_agent().connector == "cellos_acp"

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


class TestToolDefConfig:
    def test_tool_def_structure(self):
        from cellos.config import ToolDefConfig
        tool = ToolDefConfig(
            description="Submit your plan.",
            schema={
                "properties": {"objective": {"type": "string"}},
                "required": ["objective"],
            },
        )
        assert tool.description == "Submit your plan."
        assert "objective" in tool.schema_["properties"]

    def test_tool_def_default_description(self):
        from cellos.config import ToolDefConfig
        tool = ToolDefConfig(schema={"properties": {}, "required": []})
        assert tool.description == ""


class TestToolProfileConfig:
    def test_tool_profile_entry(self):
        from cellos.config import ToolProfileEntry
        entry = ToolProfileEntry(
            tools=["cellos_submit_prompt"],
            required="cellos_submit_prompt",
        )
        assert entry.tools == ["cellos_submit_prompt"]
        assert entry.required == "cellos_submit_prompt"

    def test_tool_profile_defaults(self):
        from cellos.config import ToolProfileEntry
        entry = ToolProfileEntry()
        assert entry.tools == []
        assert entry.required == ""


class TestToolRegistryConfig:
    def test_load_tool_registry(self, tmp_path):
        from cellos.config import _load_tool_registry
        tools_json = tmp_path / "tools.json"
        tools_json.write_text(json.dumps({
            "cellos_submit_prompt": {
                "description": "Submit plan.",
                "tool_schema": {"properties": {"objective": {"type": "string"}}, "required": ["objective"]},
            },
            "cellos_submit_reply": {
                "description": "Submit results.",
                "tool_schema": {"properties": {"summary": {"type": "string"}}, "required": ["summary"]},
            },
        }))
        registry = _load_tool_registry(tools_json)
        assert "cellos_submit_prompt" in registry
        assert registry["cellos_submit_prompt"].description == "Submit plan."

    def test_load_missing_tools_file(self, tmp_path):
        from cellos.config import _load_tool_registry
        registry = _load_tool_registry(tmp_path / "nonexistent.json")
        assert registry == {}


class TestToolProfilesConfig:
    def test_load_tool_profiles(self, tmp_path):
        from cellos.config import _load_tool_profiles
        profiles_json = tmp_path / "toolprofiles.json"
        profiles_json.write_text(json.dumps({
            "engineer": {
                "planning": {"tools": ["cellos_submit_prompt"], "required": "cellos_submit_prompt"},
                "execution": {"tools": ["cellos_submit_reply"], "required": "cellos_submit_reply"},
            },
        }))
        profiles = _load_tool_profiles(profiles_json)
        assert "engineer" in profiles
        assert profiles["engineer"]["planning"].required == "cellos_submit_prompt"

    def test_load_missing_profiles_file(self, tmp_path):
        from cellos.config import _load_tool_profiles
        profiles = _load_tool_profiles(tmp_path / "nonexistent.json")
        assert profiles == {}

    def test_get_tools_for_role_mode(self, tmp_path):
        from cellos.config import _load_tool_profiles, get_tools_for_role_mode
        profiles_json = tmp_path / "toolprofiles.json"
        profiles_json.write_text(json.dumps({
            "engineer": {
                "execution": {"tools": ["cellos_submit_reply", "cellos_create_task"], "required": "cellos_submit_reply"},
            },
        }))
        profiles = _load_tool_profiles(profiles_json)
        tools, required = get_tools_for_role_mode(profiles, "engineer", "execution")
        assert "cellos_submit_reply" in tools
        assert required == "cellos_submit_reply"

    def test_get_tools_missing_role(self, tmp_path):
        from cellos.config import _load_tool_profiles, get_tools_for_role_mode
        profiles_json = tmp_path / "toolprofiles.json"
        profiles_json.write_text(json.dumps({}))
        profiles = _load_tool_profiles(profiles_json)
        tools, required = get_tools_for_role_mode(profiles, "unknown", "planning")
        assert tools == []
        assert required is None

    def test_validate_tool_refs(self, tmp_path):
        from cellos.config import _load_tool_profiles, _load_tool_registry, validate_tool_profiles, ConfigError
        profiles_json = tmp_path / "toolprofiles.json"
        profiles_json.write_text(json.dumps({
            "engineer": {
                "execution": {"tools": ["cellos_submit_reply", "cellos_create_task"], "required": "cellos_submit_reply"},
            },
        }))
        profiles = _load_tool_profiles(profiles_json)
        tools_json = tmp_path / "tools.json"
        tools_json.write_text(json.dumps({
            "cellos_submit_reply": {"description": "Submit results.", "tool_schema": {}},
            "cellos_create_task": {"description": "Create task.", "tool_schema": {}},
        }))
        tools = _load_tool_registry(tools_json)
        validate_tool_profiles(profiles, tools)  # Should not raise

    def test_validate_missing_tool_ref(self, tmp_path):
        from cellos.config import _load_tool_profiles, _load_tool_registry, validate_tool_profiles, ConfigError
        profiles_json = tmp_path / "toolprofiles.json"
        profiles_json.write_text(json.dumps({
            "engineer": {
                "execution": {"tools": ["cellos_submit_reply", "cellos_unknown_tool"], "required": "cellos_submit_reply"},
            },
        }))
        profiles = _load_tool_profiles(profiles_json)
        tools_json = tmp_path / "tools.json"
        tools_json.write_text(json.dumps({
            "cellos_submit_reply": {"description": "Submit results.", "tool_schema": {}},
        }))
        tools = _load_tool_registry(tools_json)
        with pytest.raises(ConfigError, match="cellos_unknown_tool"):
            validate_tool_profiles(profiles, tools)


class TestPromptLibraryConfig:
    def test_load_prompt_library(self, tmp_path):
        from cellos.config import _load_prompt_library
        lib_json = tmp_path / "prompt_library.json"
        lib_json.write_text(json.dumps({
            "roles": {"engineer": "You are an engineer."},
            "modes": {"planning": "Plan the task."},
            "tools_header": "## Tools\n",
            "output_instruction": "Use the tool.",
        }))
        lib = _load_prompt_library(lib_json)
        assert lib.roles["engineer"] == "You are an engineer."
        assert lib.modes["planning"] == "Plan the task."

    def test_load_missing_library_file(self, tmp_path):
        from cellos.config import _load_prompt_library
        lib = _load_prompt_library(tmp_path / "nonexistent.json")
        assert lib.roles == {}
        assert lib.modes == {}


class TestConfigToolIntegration:
    def test_load_config_with_tools(self, tmp_path):
        """Full config load includes tools, profiles, and prompt library."""
        (tmp_path / "config.json").write_text(json.dumps({
            "scheduler": {"concurrent_tasks": 2},
            "prompts": {
                "tools_path": "tools.json",
                "tool_profiles_path": "toolprofiles.json",
                "library_path": "prompt_library.json",
            },
        }))
        (tmp_path / "tools.json").write_text(json.dumps({
            "cellos_submit_prompt": {
                "description": "Submit plan.",
                "tool_schema": {"properties": {"objective": {"type": "string"}}, "required": ["objective"]},
            },
        }))
        (tmp_path / "toolprofiles.json").write_text(json.dumps({
            "engineer": {
                "planning": {"tools": ["cellos_submit_prompt"], "required": "cellos_submit_prompt"},
            },
        }))
        (tmp_path / "prompt_library.json").write_text(json.dumps({
            "roles": {"engineer": "You are an engineer."},
            "modes": {"planning": "Plan."},
            "tools_header": "## Tools\n",
            "output_instruction": "Use tools.",
        }))

        from cellos.config import load_config, get_tools_for_role_mode
        cfg = load_config(str(tmp_path))
        assert "cellos_submit_prompt" in cfg.tools
        tools, required = get_tools_for_role_mode(cfg.tool_profiles, "engineer", "planning")
        assert tools == ["cellos_submit_prompt"]
        assert cfg.prompt_library.roles["engineer"] == "You are an engineer."

    def test_load_config_validates_tool_refs(self, tmp_path):
        """Config load validates tool profiles reference valid tools."""
        (tmp_path / "config.json").write_text(json.dumps({
            "prompts": {
                "tools_path": "tools.json",
                "tool_profiles_path": "toolprofiles.json",
            },
        }))
        (tmp_path / "tools.json").write_text(json.dumps({
            "cellos_submit_prompt": {
                "description": "Submit plan.",
                "tool_schema": {"properties": {}, "required": []},
            },
        }))
        (tmp_path / "toolprofiles.json").write_text(json.dumps({
            "engineer": {
                "planning": {"tools": ["cellos_submit_prompt", "cellos_fake_tool"], "required": "cellos_submit_prompt"},
            },
        }))

        from cellos.config import load_config, get_tools_for_role_mode
        cfg = load_config(str(tmp_path))
        tools, _ = get_tools_for_role_mode(cfg.tool_profiles, "engineer", "planning")
        assert tools == ["cellos_submit_prompt", "cellos_fake_tool"]

    def test_ensure_config_copies_new_files(self, tmp_path):
        """ensure_config copies tools.json, toolprofiles.json, prompt_library.json."""
        from cellos.config import ensure_config
        result = ensure_config(str(tmp_path / "config"))
        assert (result / "tools.json").exists()
        assert (result / "toolprofiles.json").exists()
        assert (result / "prompt_library.json").exists()


