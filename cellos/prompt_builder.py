"""Build prompts from configurable library fragments — zero hardcoded strings."""

from __future__ import annotations

from typing import Any


def build_task_prompt(
    task: dict[str, object],
    library: "PromptLibraryConfig",
    mode: str = "planning",
    plan: str | None = None,
    tool_defs: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Assemble a prompt from library fragments, injected tool list, and task context.

    Sections are assembled in this order (omitted when empty):
      1. Role instruction (from library.roles[role])
      2. Mode instruction (from library.modes[mode])
      3. Available tools (from tool_defs, with field names only)
      4. Task metadata: title, role, type, status
      5. Details / description
      6. Success criteria
      7. Failure criteria
      8. Comments (planning mode only)
      9. Plan text (execution mode only)
      10. Output instruction

    Args:
        task: Dict with keys like "role", "title", "status", etc.
            Accepted keys: role, title, status, task_type, details,
                          success_criteria, failure_criteria, comments.
        library: Loaded PromptLibraryConfig from config system.
        mode: Either "planning" or "execution". Determines which profile section to use.
        plan: Plan text for execution mode (saved during planning phase).
        tool_defs: Dict mapping tool name to tool definition with "description" and
            "schema" keys. Schema's "properties" keys become field names in the prompt.

    Returns:
        Fully assembled prompt string ready to send to an agent connector.
    """
    parts: list[str] = []

    # 1. Role instruction — check role_modes first (role+mode-specific override), then generic roles/modes
    role_str = str(task.get("role", ""))
    mode_key = f"{role_str}.{mode}"
    role_mode_instruction = library.role_modes.get(mode_key) if library.role_modes else None

    if role_mode_instruction:
        # Role+mode-specific instruction — replaces both generic role and mode sections
        parts.append(f"{role_mode_instruction}\n")
    else:
        # Fall back to generic role + mode instructions
        role_instruction = library.roles.get(role_str) if library.roles else None
        if not role_instruction and role_str:
            role_instruction = f"You are a {role_str} agent."
        if role_instruction:
            parts.append(f"{role_instruction}\n")

        mode_instruction = library.modes.get(mode) if library.modes else None
        if mode_instruction:
            parts.append(f"## Instructions\n{mode_instruction}\n")

    # 3. Available tools — auto-generated from tool_defs
    if tool_defs and library.tools_header:
        tools_section = library.tools_header + "\n"
        for name, defn in tool_defs.items():
            desc = defn.get("description", "")
            schema = defn.get("schema", {})
            props = schema.get("properties", {})
            field_names = list(props.keys())
            if field_names:
                fields_str = ", ".join(field_names)
                tools_section += f"\u2022 {name} — {desc} (fields: {fields_str})\n"
            else:
                tools_section += f"\u2022 {name} — {desc}\n"
        parts.append(tools_section)

    # 4. Task metadata header
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

    # 5. Details / description
    details = task.get("details") or ""
    if details.strip():
        parts.append(f"\n## Description\n{details}\n")

    # 6. Success criteria
    success_criteria = task.get("success_criteria") or ""
    if success_criteria.strip():
        parts.append(f"\n## Success Criteria\n{success_criteria}\n")

    # 7. Failure criteria
    failure_criteria = task.get("failure_criteria") or ""
    if failure_criteria.strip():
        parts.append(f"\n## Constraints (must not do)\n{failure_criteria}\n")

    # 8. Comments — planning mode only
    comments = task.get("comments")
    if comments and str(comments).strip() and mode == "planning":
        parts.append(f"\n## Comments\n{comments}\n")

    # 9. Plan text — execution mode only
    if plan and plan.strip() and mode == "execution":
        parts.append(f"\n## Approved Plan\n{plan}\n")

    # 10. Output instruction
    if library.output_instruction:
        parts.append(f"\n{library.output_instruction}")

    return "\n".join(parts).strip() + "\n"


__all__ = ["build_task_prompt"]
