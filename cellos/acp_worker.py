"""ACP worker backend."""

from pathlib import Path

from cellos.acp import exec_task, prepare_agent_invocation
from cellos.config import AgentConfig, PromptProfilesConfig
from cellos.connectors.base import PromptEnvelope
from cellos.models import Task, TaskResult
from cellos.prompt_builder import build_task_prompt


class AcpWorker:
    def __init__(
        self,
        agent_id: str,
        agent: AgentConfig,
        prompt_profiles: PromptProfilesConfig,
        timeout_seconds: int | None = None,
        debug_log_path: str | Path | None = None,
        skip_non_json_stdout: bool = True,
    ):
        self.agent_id = agent_id
        self.agent = agent
        self.prompt_profiles = prompt_profiles
        self.timeout_seconds = timeout_seconds
        self.debug_log_path = Path(debug_log_path) if debug_log_path is not None else None
        self.skip_non_json_stdout = skip_non_json_stdout

    async def run_task(self, task: Task, cwd: Path, mode: str = "execution") -> TaskResult:
        prepared = prepare_agent_invocation(
            agent_id=self.agent_id,
            agent=self.agent,
            prompt=PromptEnvelope(
                text=build_task_prompt(task, self.prompt_profiles, mode=mode),
                mode=mode,
                metadata={
                    "task_id": task.id,
                    "role": task.role.value,
                    "task_type": task.task_type.value,
                },
            ),
            workdir=cwd,
            timeout_seconds=task.timeout_seconds or self.timeout_seconds,
            debug_log_path=self.debug_log_path or Path(cwd) / ".cellos" / "logs" / "acp-debug.log",
            skip_non_json_stdout=self.skip_non_json_stdout,
        )
        result = await exec_task(
            command=prepared.launch_command,
            cwd=prepared.workdir,
            prompt=prepared.prompt.text,
            timeout_seconds=prepared.timeout_seconds,
            debug_log_path=prepared.debug_log_path,
            skip_non_json_stdout=prepared.skip_non_json_stdout,
            ignore_close_not_found=True,
        )
        return TaskResult(
            task_id=task.id,
            success=result.stop_reason in {None, "end_turn"},
            summary=result.text.strip() or f"Agent stopped with {result.stop_reason}",
            output={
                "session_id": result.session_id,
                "stop_reason": result.stop_reason,
                "event_count": len(result.events),
                "mode": mode,
                "selected_agent_id": self.agent_id,
                "connector": self.agent.connector,
                "agent_metadata": prepared.metadata,
                "result": result.result,
            },
        )
