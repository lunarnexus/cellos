import pytest

from cellos.models import AgentRole, AttentionReason, Task, TaskStatus
from cellos.pm import (
    PmChangeKind,
    PmCreatedTask,
    PmDetectedChange,
    PmSyncResult,
    PmTaskSnapshot,
    PmTaskUpdate,
    ProjectManagementAdapter,
)


class FakeAdapter:
    name = "fake"

    async def sync_known_tasks(self, tasks: list[Task]) -> PmSyncResult:
        return PmSyncResult(
            known_tasks=[
                PmTaskSnapshot(
                    provider=self.name,
                    external_id=task.id,
                    title=task.title,
                    status=task.status,
                )
                for task in tasks
            ]
        )

    async def discover_tasks(self) -> list[PmTaskSnapshot]:
        return [
            PmTaskSnapshot(
                provider=self.name,
                external_id="external-1",
                title="Discovered",
                labels=["cellos"],
            )
        ]

    async def push_update(self, update: PmTaskUpdate) -> None:
        return None

    async def create_task(self, task: Task) -> PmCreatedTask:
        return PmCreatedTask(task=task, external_id=f"external-{task.id}")


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_fake_adapter_satisfies_pm_contract():
    adapter: ProjectManagementAdapter = FakeAdapter()
    task = Task(id="task-1", title="Sync me", role=AgentRole.COORDINATOR, status=TaskStatus.APPROVED)

    result = await adapter.sync_known_tasks([task])
    discovered = await adapter.discover_tasks()
    created = await adapter.create_task(task)

    assert result.known_tasks[0].external_id == "task-1"
    assert result.known_tasks[0].status == TaskStatus.APPROVED
    assert discovered[0].labels == ["cellos"]
    assert created.external_id == "external-task-1"


def test_pm_detected_change_can_mark_attention_reason():
    change = PmDetectedChange(
        external_id="external-1",
        kind=PmChangeKind.COMMENTED,
        attention_reason=AttentionReason.HUMAN_COMMENTED,
        summary="Human asked for revision",
    )

    assert change.kind == PmChangeKind.COMMENTED
    assert change.attention_reason == AttentionReason.HUMAN_COMMENTED
