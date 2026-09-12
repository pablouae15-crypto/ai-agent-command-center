from __future__ import annotations

import re


def _contains_action(text: str, action: str) -> bool:
    """Match complete action phrases, not larger words such as commands."""
    normalized_action = action.strip()
    return re.search(
        rf"(?<!\w){re.escape(normalized_action)}(?!\w)",
        text,
    ) is not None


def classify_task_side_effect(
    title: str,
    description: str,
    explicit_level: str = "none",
) -> str:
    """Conservatively classify obvious task side effects before execution."""
    if explicit_level in {"external", "destructive"}:
        return explicit_level

    content = f"{title}\n{description}".lower()

    # Ignore explicitly negated mutation phrases so genuinely read-only
    # inspection requests are not incorrectly classified as side-effecting.
    actionable_content = content
    for phrase in (
        "do not modify",
        "do not edit",
        "do not write",
        "do not overwrite",
        "do not replace",
        "do not rename",
        "do not move",
        "do not delete",
        "do not remove",
        "do not erase",
        "do not run command",
        "do not call external service",
        "do not send email",
        "do not send the email",
        "without modifying",
        "without editing",
        "without changing",
        "without running commands",
        "without calling external services",
        "no changes",
    ):
        actionable_content = actionable_content.replace(phrase, "")

    destructive_actions = (
        "delete ",
        "remove ",
        "erase ",
        "drop ",
        "destroy ",
    )

    external_actions = (
        "replace ",
        "modify ",
        "edit ",
        "write ",
        "overwrite ",
        "rename ",
        "move ",
        "create file",
        "save file",
        "send email",
        "send the email",
        "modify calendar",
        "create calendar",
        "delete calendar",
        "deploy ",
        "install ",
        "uninstall ",
        "execute command",
        "run command",
    )

    file_or_system_target = (
        "\\" in content
        or ":\\" in content
        or ".py" in content
        or ".js" in content
        or ".ts" in content
        or ".html" in content
        or ".css" in content
        or ".json" in content
        or ".sql" in content
        or ".yaml" in content
        or ".yml" in content
        or " file" in content
        or "repository" in content
        or "database" in content
    )

    if file_or_system_target and any(
        _contains_action(actionable_content, action)
        for action in destructive_actions
    ):
        return "destructive"

    if file_or_system_target and any(
        _contains_action(actionable_content, action)
        for action in external_actions
    ):
        return "external"

    account_side_effects = (
        "send email",
        "send the email",
        "create calendar",
        "modify calendar",
        "delete calendar",
        "deploy ",
    )

    if any(
        _contains_action(actionable_content, action)
        for action in account_side_effects
    ):
        return "external"

    return "none"


def should_defer_exact_approval(
    title: str,
    description: str | None = None,
) -> bool:
    """Return true when a task should prepare behind an exact approval."""
    content = (
        title
        if description is None
        else f"{title}\n{description}"
    ).lower()

    explicit_markers = (
        "use verified replace text",
        "verified replace text",
        "verified_replace_text",
        "use verified write text file",
        "verified write text file",
        "verified_write_text_file",
    )
    if any(marker in content for marker in explicit_markers):
        return True

    # Accept natural-language variants only when they explicitly identify an
    # approved or verified write operation. Ordinary file edits do not match.
    return re.search(
        r"\b(?:apply|perform|execute|use|make)\b.{0,50}"
        r"\b(?:approved|verified)\b.{0,50}"
        r"\b(?:text replacement|replace text|write text file|file write)\b",
        content,
    ) is not None or re.search(
        r"\b(?:approved|verified)\b.{0,50}"
        r"\b(?:text replacement|replace text|write text file|file write)\b",
        content,
    ) is not None
