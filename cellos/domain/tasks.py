"""Compatibility shim for `cellos.models` task types."""

from cellos.models import Task, TaskDependency

__all__ = ["Task", "TaskDependency"]
