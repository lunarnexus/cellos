"""Worker subprocess spawning for CelloS."""

import subprocess
import sys
from pathlib import Path
from typing import Literal

from cellos.domain.tasks import Task

WorkerMode = Literal["planning", "execution"]


class WorkerSpawner:
    """Start detached background worker subprocesses."""

    def spawn(
        self,
        task: Task,
        *,
        db_path: Path,
        config_path: Path,
        workdir: Path,
        mode: WorkerMode,
    ) -> None:
        log_path = workdir / ".cellos" / "logs" / f"worker-{task.id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "cellos.cli",
            "worker",
            task.id,
            "--mode",
            mode,
            "--db",
            str(db_path),
            "--config",
            str(config_path),
            "--workdir",
            str(workdir),
        ]
        with log_path.open("ab") as log:
            subprocess.Popen(
                command,
                cwd=workdir,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
