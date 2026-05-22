"""WorkerSpawner — spawn detached worker subprocesses with log file output.

Workers run as independent Python processes via ``cellos.cli worker`` command,
each with their own SQLite connection and PYTHONPATH for package importability.
Spawned with ``start_new_session=True`` so they're fully detached from the parent.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class WorkerSpawner:
    """Spawn worker subprocesses as detached processes.

    Each spawned process runs ``python -m cellos.cli worker <task_id> --mode ...``,
    with all stdout/stderr redirected to a log file in the project directory.

    Args:
        logs_dir: Directory for worker log files (default: current working dir).
        python_executable: Python interpreter to use (default: sys.executable).
    """

    def __init__(
        self,
        logs_dir: str = ".",
        python_executable: str | None = None,
    ):
        self.logs_dir = Path(logs_dir)
        self.python = python_executable or sys.executable

    def spawn(
        self,
        task_id: str,
        mode: str,  # "planning" or "execution"
        db_path: str | None = None,
        config_dir: str | None = None,
        workdir: str | None = None,
    ) -> subprocess.Popen:
        """Spawn a detached worker subprocess.

        The spawned process is fully independent — no shared memory or state with
        the parent scheduler. All coordination happens through SQLite.

        Args:
            task_id: ID of the task to execute.
            mode: "planning" or "execution".
            db_path: Path to SQLite database (passed as --db flag).
            config_dir: Config directory path (passed as --config-dir flag).
            workdir: Working directory for the worker subprocess.

        Returns:
            Popen process handle (detached, not tracked by parent).
        """
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.logs_dir / f"worker-{task_id}.log"

        # --db and --config-dir are group-level options, must come before subcommand
        cmd = [self.python, "-m", "cellos.cli"]

        if db_path:
            cmd.extend(["--db", str(db_path)])
        if config_dir:
            cmd.extend(["--config-dir", str(config_dir)])

        cmd.extend(["worker", task_id, "--mode", mode])

        env = os.environ.copy()
        # Inject PYTHONPATH so the package is importable in spawned subprocess
        cwd_for_path = workdir or "."
        existing_paths = env.get("PYTHONPATH", "")
        paths_list = [cwd_for_path] + (existing_paths.split(":") if existing_paths else [])
        env["PYTHONPATH"] = ":".join(paths_list)

        logger.info(
            "Spawning worker for task %s mode=%s log=%s cmd='%s'",
            task_id, mode, log_file, " ".join(cmd),
        )

        with open(log_file, "w", encoding="utf-8") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,  # Merge stderr into stdout (log file)
                cwd=workdir or ".",
                env=env,
                start_new_session=True,  # Detach from parent process group
            )

        logger.info("Worker spawned: pid=%d task=%s", proc.pid, task_id)
        return proc


__all__ = ["WorkerSpawner"]
