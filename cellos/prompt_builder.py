"""Prompt construction for CelloS agent turns."""

from cellos.config import PromptProfilesConfig
from cellos.domain.tasks import Task


def build_task_prompt(
    task: Task,
    profiles: PromptProfilesConfig,
    mode: str = "execution",
    comments: list[dict] | None = None,
) -> str:
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
    if mode == "planning" and comments:
        research_results = [_format_comment(comment) for comment in comments if _is_research_result(comment)]
        normal_comments = [_format_comment(comment) for comment in comments if not _is_research_result(comment)]
        if normal_comments:
            parts.extend(["Comments:", *normal_comments, ""])
        if research_results:
            parts.extend(["Research Results:", *research_results, ""])
    if mode == "planning" and task.conversation:
        parts.append("Conversation:")
        for msg in task.conversation:
            parts.append(f"- {msg.author}: {msg.message}")
        parts.append("")
    if mode_profile is not None and mode_profile.output_sections:
        parts.extend(["Response format:", "Return Markdown using these sections:"])
        parts.extend([f"- {section}" for section in mode_profile.output_sections])
        parts.append("")
    if profiles.final_instructions:
        parts.extend(profiles.final_instructions)
    return "\n".join(parts)


def _is_research_result(comment: dict) -> bool:
    payload = comment.get("payload")
    if not isinstance(payload, dict):
        return False
    return payload.get("kind") == "research_result"


def _format_comment(comment: dict) -> str:
    author = comment.get("author_id") or comment.get("author_type") or "unknown"
    message = str(comment.get("message") or "").strip()
    return f"- {author}: {message}"
