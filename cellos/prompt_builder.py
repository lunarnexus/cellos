"""Build prompts from configurable profiles — zero hardcoded strings."""

from __future__ import annotations


def build_task_prompt(
    task: dict[str, object],
    profiles: "PromptProfilesConfig",
    mode: str = "planning",
    plan: str | None = None,
) -> str:
    """Assemble a prompt from configurable profile parts and task context.

    Sections are assembled in this order (omitted when empty):
      1. Role instruction (from profiles.role_instructions[role])
      2. Mode-specific instructions (profiles.modes[mode].instructions)
      3. Task metadata: title, role, type, status
      4. Details / description
      5. Success criteria
      6. Failure criteria
      7. Plan text (execution mode only — passed as ``plan`` arg)
      8. Output sections format requirement (profiles.modes[mode].output_sections)
      9. Final instructions

    Args:
        task: Dict with keys like "role", "title", "status", etc.
            Accepted keys: role, title, status, task_type, details,
                          success_criteria, failure_criteria.
        profiles: Loaded PromptProfilesConfig from config system.
        mode: Either "planning" or "execution". Determines which profile section to use.
        plan: Plan text for execution mode (saved during planning phase).

    Returns:
        Fully assembled prompt string ready to send to an agent connector.
    """
    parts: list[str] = []

    # 1. Role instruction
    role_str = str(task.get("role", ""))
    role_instruction = profiles.role_instructions.get(role_str) or (
        f"You are a {role_str} agent." if role_str else None
    )
    if role_instruction:
        parts.append(f"{role_instruction}\n")

    # 2. Mode-specific instructions
    mode_profile = profiles.modes.get(mode)
    if mode_profile and mode_profile.instructions:
        parts.append(f"## Instructions\n{mode_profile.instructions}\n")

    # 3. Task metadata header
    title = task.get("title", "")
    role_label = str(task.get("role", ""))
    type_label = str(task.get("task_type", ""))
    status_label = str(task.get("status", ""))
    parts.append(
        f"## Task\n- Title: {title}\n"
        f"- Role: {role_label}\n"
        f"- Type: {type_label}\n"
        f"- Status: {status_label}\n"
    )

    # 4. Details / description
    details = task.get("details") or ""
    if details.strip():
        parts.append(f"\n## Description\n{details}\n")

    # 5. Success criteria
    success_criteria = task.get("success_criteria") or ""
    if success_criteria.strip():
        parts.append(f"\n## Success Criteria\n{success_criteria}\n")

    # 6. Failure criteria
    failure_criteria = task.get("failure_criteria") or ""
    if failure_criteria.strip():
        parts.append(f"\n## Constraints (must not do)\n{failure_criteria}\n")

    # 6.5. Comments — planning mode only
    comments = task.get("comments")
    if comments and str(comments).strip() and mode == "planning":
        parts.append(f"\n## Comments\n{comments}\n")

    # 7. Plan text — execution mode only
    if plan and plan.strip() and mode == "execution":
        parts.append(f"\n## Approved Plan\n{plan}\n")

    # 8. Output sections format requirement
    if mode_profile and mode_profile.output_sections:
        section_list = ", ".join(mode_profile.output_sections)
        parts.append(
            f"\n## Response Format\n"
            "Structure your response using these sections:\n"
            f"{section_list}\n"
        )

    # 9. Final instructions (always included if non-empty — contains action format docs)
    if profiles.final_instructions:
        parts.append(f"\n{profiles.final_instructions}")

    return "\n".join(parts).strip() + "\n"


__all__ = ["build_task_prompt"]
