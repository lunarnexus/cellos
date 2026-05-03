"""Prompt construction for CelloS agent turns."""

from cellos.config import PromptProfilesConfig
from cellos.models import Task


def build_task_prompt(task: Task, profiles: PromptProfilesConfig, mode: str = "execution") -> str:
    mode_profile = profiles.modes.get(mode) or profiles.modes.get("execution")
    role_instruction = profiles.role_instructions.get(task.role.value, "")
    parts = [
        f"Role: {task.role.value}",
        f"Task type: {task.task_type.value}",
        f"Title: {task.title}",
        f"Status: {task.status.value}",
        "",
    ]
    if role_instruction:
        parts.extend(["Role instructions:", role_instruction, ""])
    if mode_profile is not None and mode_profile.instructions:
        parts.extend(mode_profile.instructions)
        parts.append("")
    if task.prompt.strip():
        parts.extend(["Task prompt / approved scope:", task.prompt.strip(), ""])
    if task.description.strip():
        parts.extend(["Additional description:", task.description.strip(), ""])
    if mode_profile is not None and mode_profile.output_sections:
        parts.extend(["Response format:", "Return Markdown using these sections:"])
        parts.extend([f"- {section}" for section in mode_profile.output_sections])
        parts.append("")
    if profiles.final_instructions:
        parts.extend(profiles.final_instructions)
    return "\n".join(parts)
