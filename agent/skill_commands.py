"""Shared slash command helpers for skills and built-in prompt-style modes.

Shared between CLI (cli.py) and gateway (gateway/run.py) so both surfaces
can invoke skills via /skill-name commands and prompt-only built-ins like
/plan.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from agent.skill_analytics import log_skill_event

logger = logging.getLogger(__name__)

_skill_commands: Dict[str, Dict[str, Any]] = {}
_PLAN_SLUG_RE = re.compile(r"[^a-z0-9]+")
# Patterns for sanitizing skill names into clean hyphen-separated slugs.
_SKILL_INVALID_CHARS = re.compile(r"[^a-z0-9-]")
_SKILL_MULTI_HYPHEN = re.compile(r"-{2,}")


def build_plan_path(
    user_instruction: str = "",
    *,
    now: datetime | None = None,
) -> Path:
    """Return the default workspace-relative markdown path for a /plan invocation.

    Relative paths are intentional: file tools are task/backend-aware and resolve
    them against the active working directory for local, docker, ssh, modal,
    daytona, and similar terminal backends. That keeps the plan with the active
    workspace instead of the Hermes host's global home directory.
    """
    slug_source = (user_instruction or "").strip().splitlines()[0] if user_instruction else ""
    slug = _PLAN_SLUG_RE.sub("-", slug_source.lower()).strip("-")
    if slug:
        slug = "-".join(part for part in slug.split("-")[:8] if part)[:48].strip("-")
    slug = slug or "conversation-plan"
    timestamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    return Path(".hermes") / "plans" / f"{timestamp}-{slug}.md"


def _load_skill_payload(skill_identifier: str, task_id: str | None = None) -> tuple[dict[str, Any], Path | None, str] | None:
    """Load a skill by name/path and return (loaded_payload, skill_dir, display_name)."""
    raw_identifier = (skill_identifier or "").strip()
    if not raw_identifier:
        return None

    try:
        from tools.skills_tool import SKILLS_DIR, skill_view

        identifier_path = Path(raw_identifier).expanduser()
        if identifier_path.is_absolute():
            try:
                normalized = str(identifier_path.resolve().relative_to(SKILLS_DIR.resolve()))
            except Exception:
                normalized = raw_identifier
        else:
            normalized = raw_identifier.lstrip("/")

        loaded_skill = json.loads(skill_view(normalized, task_id=task_id))
    except Exception:
        return None

    if not loaded_skill.get("success"):
        return None

    skill_name = str(loaded_skill.get("name") or normalized)
    skill_path = str(loaded_skill.get("path") or "")
    skill_dir = None
    if skill_path:
        try:
            skill_dir = SKILLS_DIR / Path(skill_path).parent
        except Exception:
            skill_dir = None

    return loaded_skill, skill_dir, skill_name


def _inject_skill_config(loaded_skill: dict[str, Any], parts: list[str]) -> None:
    """Resolve and inject skill-declared config values into the message parts.

    If the loaded skill's frontmatter declares ``metadata.hermes.config``
    entries, their current values (from config.yaml or defaults) are appended
    as a ``[Skill config: ...]`` block so the agent knows the configured values
    without needing to read config.yaml itself.
    """
    try:
        from agent.skill_utils import (
            extract_skill_config_vars,
            parse_frontmatter,
            resolve_skill_config_values,
        )

        # The loaded_skill dict contains the raw content which includes frontmatter
        raw_content = str(loaded_skill.get("raw_content") or loaded_skill.get("content") or "")
        if not raw_content:
            return

        frontmatter, _ = parse_frontmatter(raw_content)
        config_vars = extract_skill_config_vars(frontmatter)
        if not config_vars:
            return

        resolved = resolve_skill_config_values(config_vars)
        if not resolved:
            return

        lines = ["", "[Skill config (from ~/.hermes/config.yaml):"]
        for key, value in resolved.items():
            display_val = str(value) if value else "(not set)"
            lines.append(f"  {key} = {display_val}")
        lines.append("]")
        parts.extend(lines)
    except Exception:
        pass  # Non-critical — skill still loads without config injection


def _build_skill_message(
    loaded_skill: dict[str, Any],
    skill_dir: Path | None,
    activation_note: str,
    user_instruction: str = "",
    runtime_note: str = "",
) -> str:
    """Format a loaded skill into a user/system message payload."""
    from tools.skills_tool import SKILLS_DIR

    content = str(loaded_skill.get("content") or "")

    parts = [activation_note, "", content.strip()]

    workflow = loaded_skill.get("workflow") or {}
    if isinstance(workflow, dict) and workflow:
        lines = ["", "[Skill workflow]"]
        if workflow.get("name"):
            lines.append(f"Name: {workflow['name']}")
        for label, key in (
            ("Steps", "steps"),
            ("Verification", "verification"),
            ("Deliverables", "deliverables"),
        ):
            values = workflow.get(key)
            if isinstance(values, list) and values:
                lines.append(f"{label}:")
                lines.extend(f"- {item}" for item in values)
        parts.extend(lines)

    # ── Inject resolved skill config values ──
    _inject_skill_config(loaded_skill, parts)

    if loaded_skill.get("setup_skipped"):
        parts.extend(
            [
                "",
                "[Skill setup note: Required environment setup was skipped. Continue loading the skill and explain any reduced functionality if it matters.]",
            ]
        )
    elif loaded_skill.get("gateway_setup_hint"):
        parts.extend(
            [
                "",
                f"[Skill setup note: {loaded_skill['gateway_setup_hint']}]",
            ]
        )
    elif loaded_skill.get("setup_needed") and loaded_skill.get("setup_note"):
        parts.extend(
            [
                "",
                f"[Skill setup note: {loaded_skill['setup_note']}]",
            ]
        )

    supporting = []
    linked_files = loaded_skill.get("linked_files") or {}
    for entries in linked_files.values():
        if isinstance(entries, list):
            supporting.extend(entries)

    if not supporting and skill_dir:
        for subdir in ("references", "templates", "scripts", "assets"):
            subdir_path = skill_dir / subdir
            if subdir_path.exists():
                for f in sorted(subdir_path.rglob("*")):
                    if f.is_file() and not f.is_symlink():
                        rel = str(f.relative_to(skill_dir))
                        supporting.append(rel)

    if supporting and skill_dir:
        try:
            skill_view_target = str(skill_dir.relative_to(SKILLS_DIR))
        except ValueError:
            # Skill is from an external dir — use the skill name instead
            skill_view_target = skill_dir.name
        parts.append("")
        parts.append("[This skill has supporting files you can load with the skill_view tool:]")
        for sf in supporting:
            parts.append(f"- {sf}")
        parts.append(
            f'\nTo view any of these, use: skill_view(name="{skill_view_target}", file_path="<path>")'
        )

    if user_instruction:
        parts.append("")
        parts.append(f"The user has provided the following instruction alongside the skill invocation: {user_instruction}")

    if runtime_note:
        parts.append("")
        parts.append(f"[Runtime note: {runtime_note}]")

    return "\n".join(parts)


def _expand_skill_payloads(
    skill_identifiers: list[str],
    *,
    task_id: str | None = None,
) -> tuple[list[tuple[dict[str, Any], Path | None, str, str | None]], list[str], list[str]]:
    """Resolve skills plus declared related_skills into an operational chain.

    Returns tuples of ``(loaded_skill, skill_dir, skill_name, parent_skill_name)``
    in load order, along with the loaded names and any missing root identifiers.
    Related skills are best-effort: missing related skills are skipped instead of
    being reported as hard failures.
    """
    expanded: list[tuple[dict[str, Any], Path | None, str, str | None]] = []
    loaded_names: list[str] = []
    missing_roots: list[str] = []
    seen_identifiers: set[str] = set()
    seen_skill_names: set[str] = set()

    def _visit(identifier: str, parent_skill_name: str | None = None, *, is_root: bool = False) -> None:
        normalized_identifier = (identifier or "").strip()
        if not normalized_identifier or normalized_identifier in seen_identifiers:
            return
        seen_identifiers.add(normalized_identifier)

        loaded = _load_skill_payload(normalized_identifier, task_id=task_id)
        if not loaded:
            if is_root:
                missing_roots.append(normalized_identifier)
            return

        loaded_skill, skill_dir, skill_name = loaded
        if skill_name in seen_skill_names:
            return
        seen_skill_names.add(skill_name)
        expanded.append((loaded_skill, skill_dir, skill_name, parent_skill_name))
        loaded_names.append(skill_name)

        related = loaded_skill.get("related_skills") or []
        if isinstance(related, list):
            for related_name in related:
                _visit(str(related_name), skill_name)

    for raw_identifier in skill_identifiers:
        _visit(raw_identifier, is_root=True)

    return expanded, loaded_names, missing_roots


def scan_skill_commands() -> Dict[str, Dict[str, Any]]:
    """Scan ~/.hermes/skills/ and return a mapping of /command -> skill info.

    Returns:
        Dict mapping "/skill-name" to {name, description, skill_md_path, skill_dir}.
    """
    global _skill_commands
    _skill_commands = {}
    try:
        from tools.skills_tool import SKILLS_DIR, _parse_frontmatter, skill_matches_platform, _get_disabled_skill_names
        from agent.skill_utils import get_external_skills_dirs
        disabled = _get_disabled_skill_names()
        seen_names: set = set()

        # Scan local dir first, then external dirs
        dirs_to_scan = []
        if SKILLS_DIR.exists():
            dirs_to_scan.append(SKILLS_DIR)
        dirs_to_scan.extend(get_external_skills_dirs())

        for scan_dir in dirs_to_scan:
            for skill_md in scan_dir.rglob("SKILL.md"):
                if any(part in ('.git', '.github', '.hub') for part in skill_md.parts):
                    continue
                try:
                    content = skill_md.read_text(encoding='utf-8')
                    frontmatter, body = _parse_frontmatter(content)
                    # Skip skills incompatible with the current OS platform
                    if not skill_matches_platform(frontmatter):
                        continue
                    name = frontmatter.get('name', skill_md.parent.name)
                    if name in seen_names:
                        continue
                    # Respect user's disabled skills config
                    if name in disabled:
                        continue
                    description = frontmatter.get('description', '')
                    if not description:
                        for line in body.strip().split('\n'):
                            line = line.strip()
                            if line and not line.startswith('#'):
                                description = line[:80]
                                break
                    seen_names.add(name)
                    # Normalize to hyphen-separated slug, stripping
                    # non-alnum chars (e.g. +, /) to avoid invalid
                    # Telegram command names downstream.
                    cmd_name = name.lower().replace(' ', '-').replace('_', '-')
                    cmd_name = _SKILL_INVALID_CHARS.sub('', cmd_name)
                    cmd_name = _SKILL_MULTI_HYPHEN.sub('-', cmd_name).strip('-')
                    if not cmd_name:
                        continue
                    _skill_commands[f"/{cmd_name}"] = {
                        "name": name,
                        "description": description or f"Invoke the {name} skill",
                        "skill_md_path": str(skill_md),
                        "skill_dir": str(skill_md.parent),
                    }
                except Exception:
                    continue
    except Exception:
        pass
    return _skill_commands


def get_skill_commands() -> Dict[str, Dict[str, Any]]:
    """Return the current skill commands mapping (scan first if empty)."""
    if not _skill_commands:
        scan_skill_commands()
    return _skill_commands


def resolve_skill_command_key(command: str) -> Optional[str]:
    """Resolve a user-typed /command to its canonical skill_cmds key.

    Skills are always stored with hyphens — ``scan_skill_commands`` normalizes
    spaces and underscores to hyphens when building the key. Hyphens and
    underscores are treated interchangeably in user input: this matches
    ``_check_unavailable_skill`` and accommodates Telegram bot-command names
    (which disallow hyphens, so ``/claude-code`` is registered as
    ``/claude_code`` and comes back in the underscored form).

    Returns the matching ``/slug`` key from ``get_skill_commands()`` or
    ``None`` if no match.
    """
    if not command:
        return None
    cmd_key = f"/{command.replace('_', '-')}"
    return cmd_key if cmd_key in get_skill_commands() else None


def build_skill_invocation_message(
    cmd_key: str,
    user_instruction: str = "",
    task_id: str | None = None,
    runtime_note: str = "",
) -> Optional[str]:
    """Build the user message content for a skill slash command invocation.

    Args:
        cmd_key: The command key including leading slash (e.g., "/gif-search").
        user_instruction: Optional text the user typed after the command.

    Returns:
        The formatted message string, or None if the skill wasn't found.
    """
    commands = get_skill_commands()
    skill_info = commands.get(cmd_key)
    if not skill_info:
        return None

    loaded_payloads, _, _ = _expand_skill_payloads([skill_info["skill_dir"]], task_id=task_id)
    if not loaded_payloads:
        return f"[Failed to load skill: {skill_info['name']}]"

    message_parts: list[str] = []
    for index, (loaded_skill, skill_dir, skill_name, parent_skill_name) in enumerate(loaded_payloads):
        if index == 0:
            activation_note = (
                f'[SYSTEM: The user has invoked the "{skill_name}" skill, indicating they want '
                "you to follow its instructions. The full skill content is loaded below.]"
            )
            chained_user_instruction = user_instruction
            log_skill_event(
                skill_name=skill_name,
                event_type="invoked",
                session_id=task_id,
                trigger="slash_command",
                metadata={"command": cmd_key, "has_instruction": bool(user_instruction)},
            )
        else:
            activation_note = (
                f'[SYSTEM: The "{parent_skill_name}" skill declares "{skill_name}" as a related skill. '
                "Treat the following as additional guidance automatically chained from the related skill graph.]"
            )
            chained_user_instruction = ""
            log_skill_event(
                skill_name=skill_name,
                event_type="chained",
                session_id=task_id,
                trigger="auto_chain",
                parent_skill_name=parent_skill_name,
                metadata={"command": cmd_key},
            )
        message_parts.append(
            _build_skill_message(
                loaded_skill,
                skill_dir,
                activation_note,
                user_instruction=chained_user_instruction,
                runtime_note=runtime_note if index == 0 else "",
            )
        )
    return "\n\n".join(message_parts)


def build_preloaded_skills_prompt(
    skill_identifiers: list[str],
    task_id: str | None = None,
) -> tuple[str, list[str], list[str]]:
    """Load one or more skills for session-wide CLI preloading.

    Returns (prompt_text, loaded_skill_names, missing_identifiers).
    """
    prompt_parts: list[str] = []
    expanded_payloads, loaded_names, missing = _expand_skill_payloads(
        skill_identifiers,
        task_id=task_id,
    )

    for loaded_skill, skill_dir, skill_name, parent_skill_name in expanded_payloads:
        if parent_skill_name:
            activation_note = (
                f'[SYSTEM: The "{parent_skill_name}" skill declares "{skill_name}" as a related skill. '
                "Treat its instructions as additional guidance automatically chained from the related skill graph.]"
            )
            log_skill_event(
                skill_name=skill_name,
                event_type="chained",
                session_id=task_id,
                trigger="auto_chain",
                parent_skill_name=parent_skill_name,
                metadata={"preloaded": True},
            )
        else:
            activation_note = (
                f'[SYSTEM: The user launched this CLI session with the "{skill_name}" skill '
                "preloaded. Treat its instructions as active guidance for the duration of this "
                "session unless the user overrides them.]"
            )
            log_skill_event(
                skill_name=skill_name,
                event_type="preloaded",
                session_id=task_id,
                trigger="preload_flag",
            )
        prompt_parts.append(
            _build_skill_message(
                loaded_skill,
                skill_dir,
                activation_note,
            )
        )

    return "\n\n".join(prompt_parts), loaded_names, missing
