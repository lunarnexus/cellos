"""Worker backend interfaces."""

from pathlib import Path
from typing import Protocol

from cellos.models import Task, TaskResult


class TaskWorker(Protocol):
    async def run_task(self, task: Task, cwd: Path, mode: str = "execution") -> TaskResult: ...
