#!/usr/bin/env python3
"""
Memory Tool Module - Persistent Curated Memory

Provides bounded, file-backed memory that persists across sessions. Two stores:
  - MEMORY.md: agent's personal notes and observations (environment facts, project
    conventions, tool quirks, things learned)
  - USER.md: what the agent knows about the user (preferences, communication style,
    expectations, workflow habits)

Both are injected into the system prompt as a frozen snapshot at session start.
Mid-session writes update files on disk immediately (durable) but do NOT change
the system prompt -- this preserves the prefix cache for the entire session.
The snapshot refreshes on the next session start.

Entry delimiter: § (section sign). Entries can be multiline.
Character limits (not tokens) because char counts are model-independent.

Design:
- Single `memory` tool with action parameter: add, replace, remove, read
- replace/remove use short unique substring matching (not full text or IDs)
- Behavioral guidance lives in the tool schema description
- Frozen snapshot pattern: system prompt is stable, tool responses show live state
"""

import fcntl
import json
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from hermes_constants import get_hermes_home
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Where memory files live — resolved dynamically so profile overrides
# (HERMES_HOME env var changes) are always respected.  The old module-level
# constant was cached at import time and could go stale if a profile switch
# happened after the first import.
def get_memory_dir() -> Path:
    """Return the profile-scoped memories directory."""
    return get_hermes_home() / "memories"

# Backward-compatible alias — gateway/run.py imports this at runtime inside
# a function body, so it gets the correct snapshot for that process.  New code
# should prefer get_memory_dir().
MEMORY_DIR = get_memory_dir()

ENTRY_DELIMITER = "\n§\n"
DEFAULT_MEMORY_CLASS = "other"
MEMORY_CLASSES_BY_TARGET = {
    "memory": {"environment", "tooling", "workflow", "project", "convention", "correction", DEFAULT_MEMORY_CLASS},
    "user": {"identity", "preference", "profile", "communication", "workflow", DEFAULT_MEMORY_CLASS},
}
_SERIALIZED_CLASS_PREFIX_RE = re.compile(r"^\[memory_class=([a-z_]+)\]\n(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class MemoryRecord:
    content: str
    memory_class: str = DEFAULT_MEMORY_CLASS

    def to_dict(self) -> Dict[str, str]:
        return {"content": self.content, "memory_class": self.memory_class}


def _normalize_memory_class(target: str, entry_class: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    normalized = str(entry_class or DEFAULT_MEMORY_CLASS).strip().lower() or DEFAULT_MEMORY_CLASS
    valid = MEMORY_CLASSES_BY_TARGET.get(target)
    if not valid:
        return None, f"Invalid target '{target}'."
    if normalized not in valid:
        choices = ", ".join(sorted(valid))
        return None, f"Invalid memory_class '{normalized}' for target '{target}'. Valid classes: {choices}."
    return normalized, None


def _serialize_record(record: MemoryRecord) -> str:
    if record.memory_class == DEFAULT_MEMORY_CLASS:
        return record.content
    return f"[memory_class={record.memory_class}]\n{record.content}"


def _deserialize_record(raw_entry: str) -> MemoryRecord:
    text = raw_entry.strip()
    match = _SERIALIZED_CLASS_PREFIX_RE.match(text)
    if not match:
        return MemoryRecord(content=text, memory_class=DEFAULT_MEMORY_CLASS)
    return MemoryRecord(content=match.group(2).strip(), memory_class=match.group(1).strip().lower() or DEFAULT_MEMORY_CLASS)


# ---------------------------------------------------------------------------
# Memory content scanning — lightweight check for injection/exfiltration
# in content that gets injected into the system prompt.
# ---------------------------------------------------------------------------

_MEMORY_THREAT_PATTERNS = [
    # Prompt injection
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (r'act\s+as\s+(if|though)\s+you\s+(have\s+no|don\'t\s+have)\s+(restrictions|limits|rules)', "bypass_restrictions"),
    # Exfiltration via curl/wget with secrets
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets"),
    # Persistence via shell rc
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access"),
    (r'\$HOME/\.hermes/\.env|\~/\.hermes/\.env', "hermes_env"),
]

# Subset of invisible chars for injection detection
_INVISIBLE_CHARS = {
    '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
}


def _scan_memory_content(content: str) -> Optional[str]:
    """Scan memory content for injection/exfil patterns. Returns error string if blocked."""
    # Check invisible unicode
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"Blocked: content contains invisible unicode character U+{ord(char):04X} (possible injection)."

    # Check threat patterns
    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Blocked: content matches threat pattern '{pid}'. Memory entries are injected into the system prompt and must not contain injection or exfiltration payloads."

    return None


class MemoryStore:
    """
    Bounded curated memory with file persistence. One instance per AIAgent.

    Maintains two parallel states:
      - _system_prompt_snapshot: frozen at load time, used for system prompt injection.
        Never mutated mid-session. Keeps prefix cache stable.
      - memory_entries / user_entries: live state, mutated by tool calls, persisted to disk.
        Tool responses always reflect this live state.
    """

    def __init__(self, memory_char_limit: int = 2200, user_char_limit: int = 1375):
        self._memory_records: List[MemoryRecord] = []
        self._user_records: List[MemoryRecord] = []
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        # Frozen snapshot for system prompt -- set once at load_from_disk()
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}

    @property
    def memory_entries(self) -> List[str]:
        return [record.content for record in self._memory_records]

    @property
    def user_entries(self) -> List[str]:
        return [record.content for record in self._user_records]

    @property
    def memory_records(self) -> List[MemoryRecord]:
        return list(self._memory_records)

    @property
    def user_records(self) -> List[MemoryRecord]:
        return list(self._user_records)

    def load_from_disk(self):
        """Load entries from MEMORY.md and USER.md, capture system prompt snapshot."""
        mem_dir = get_memory_dir()
        mem_dir.mkdir(parents=True, exist_ok=True)

        self._memory_records = self._dedupe_records(self._read_records(mem_dir / "MEMORY.md"))
        self._user_records = self._dedupe_records(self._read_records(mem_dir / "USER.md"))

        # Capture frozen snapshot for system prompt injection
        self._system_prompt_snapshot = {
            "memory": self._render_block("memory", self.memory_entries),
            "user": self._render_block("user", self.user_entries),
        }

    @staticmethod
    @contextmanager
    def _file_lock(path: Path):
        """Acquire an exclusive file lock for read-modify-write safety.

        Uses a separate .lock file so the memory file itself can still be
        atomically replaced via os.replace().
        """
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(lock_path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    @staticmethod
    def _path_for(target: str) -> Path:
        mem_dir = get_memory_dir()
        if target == "user":
            return mem_dir / "USER.md"
        return mem_dir / "MEMORY.md"

    def _reload_target(self, target: str):
        """Re-read entries from disk into in-memory state.

        Called under file lock to get the latest state before mutating.
        """
        fresh = self._dedupe_records(self._read_records(self._path_for(target)))
        self._set_records(target, fresh)

    def save_to_disk(self, target: str):
        """Persist entries to the appropriate file. Called after every mutation."""
        get_memory_dir().mkdir(parents=True, exist_ok=True)
        self._write_records(self._path_for(target), self._records_for(target))

    def _records_for(self, target: str) -> List[MemoryRecord]:
        if target == "user":
            return list(self._user_records)
        return list(self._memory_records)

    def _set_records(self, target: str, records: List[MemoryRecord]):
        if target == "user":
            self._user_records = list(records)
        else:
            self._memory_records = list(records)

    def _entries_for(self, target: str) -> List[str]:
        return [record.content for record in self._records_for(target)]

    def _structured_entries_for(self, target: str) -> List[Dict[str, str]]:
        return [record.to_dict() for record in self._records_for(target)]

    def _char_count(self, target: str) -> int:
        entries = self._entries_for(target)
        if not entries:
            return 0
        return len(ENTRY_DELIMITER.join(entries))

    def _char_limit(self, target: str) -> int:
        if target == "user":
            return self.user_char_limit
        return self.memory_char_limit

    @staticmethod
    def _dedupe_records(records: List[MemoryRecord]) -> List[MemoryRecord]:
        seen = set()
        deduped: List[MemoryRecord] = []
        for record in records:
            key = (record.content, record.memory_class)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
        return deduped

    def add(self, target: str, content: str, entry_class: Optional[str] = None) -> Dict[str, Any]:
        """Append a new entry. Returns error if it would exceed the char limit."""
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}

        normalized_class, class_error = _normalize_memory_class(target, entry_class)
        if class_error:
            return {"success": False, "error": class_error}

        # Scan for injection/exfiltration before accepting
        scan_error = _scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._file_lock(self._path_for(target)):
            # Re-read from disk under lock to pick up writes from other sessions
            self._reload_target(target)

            records = self._records_for(target)
            entries = [record.content for record in records]
            limit = self._char_limit(target)

            # Reject exact duplicates
            if content in entries:
                result = self._success_response(target, "Entry already exists (no duplicate added).")
                duplicate_record = next((record for record in records if record.content == content), None)
                if duplicate_record is not None:
                    result["entry"] = duplicate_record.to_dict()
                result["changed"] = False
                return result

            # Calculate what the new total would be
            new_entries = entries + [content]
            new_total = len(ENTRY_DELIMITER.join(new_entries))

            if new_total > limit:
                current = self._char_count(target)
                return {
                    "success": False,
                    "error": (
                        f"Memory at {current:,}/{limit:,} chars. "
                        f"Adding this entry ({len(content)} chars) would exceed the limit. "
                        f"Replace or remove existing entries first."
                    ),
                    "current_entries": entries,
                    "usage": f"{current:,}/{limit:,}",
                }

            records.append(MemoryRecord(content=content, memory_class=normalized_class or DEFAULT_MEMORY_CLASS))
            self._set_records(target, records)
            self.save_to_disk(target)

        result = self._success_response(target, "Entry added.")
        result["entry"] = records[-1].to_dict()
        result["changed"] = True
        return result

    def replace(self, target: str, old_text: str, new_content: str, entry_class: Optional[str] = None) -> Dict[str, Any]:
        """Find entry containing old_text substring, replace it with new_content."""
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}
        if not new_content:
            return {"success": False, "error": "new_content cannot be empty. Use 'remove' to delete entries."}

        normalized_class = None
        if entry_class is not None:
            normalized_class, class_error = _normalize_memory_class(target, entry_class)
            if class_error:
                return {"success": False, "error": class_error}

        # Scan replacement content for injection/exfiltration
        scan_error = _scan_memory_content(new_content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._file_lock(self._path_for(target)):
            self._reload_target(target)

            records = self._records_for(target)
            entries = [record.content for record in records]
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}

            if len(matches) > 1:
                # If all matches are identical, only auto-resolve when their
                # structured classes are also identical. Same content with
                # different classes is ambiguous in the structured model.
                unique_texts = set(e for _, e in matches)
                if len(unique_texts) > 1:
                    previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                    return {
                        "success": False,
                        "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                        "matches": previews,
                    }
                unique_classes = {records[i].memory_class for i, _ in matches}
                if len(unique_classes) > 1:
                    return {
                        "success": False,
                        "error": (
                            f"Multiple structured entries matched '{old_text}' with different classes. "
                            "Be more specific."
                        ),
                        "matches": [records[i].to_dict() for i, _ in matches],
                    }
                # All identical text/class duplicates -- safe to replace just the first

            idx = matches[0][0]
            limit = self._char_limit(target)

            # Check that replacement doesn't blow the budget
            test_entries = entries.copy()
            test_entries[idx] = new_content
            new_total = len(ENTRY_DELIMITER.join(test_entries))

            if new_total > limit:
                return {
                    "success": False,
                    "error": (
                        f"Replacement would put memory at {new_total:,}/{limit:,} chars. "
                        f"Shorten the new content or remove other entries first."
                    ),
                }

            current_class = records[idx].memory_class
            records[idx] = MemoryRecord(
                content=new_content,
                memory_class=normalized_class or current_class,
            )
            self._set_records(target, records)
            self.save_to_disk(target)

        result = self._success_response(target, "Entry replaced.")
        result["entry"] = records[idx].to_dict()
        result["changed"] = True
        return result

    def remove(self, target: str, old_text: str) -> Dict[str, Any]:
        """Remove the entry containing old_text substring."""
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}

        with self._file_lock(self._path_for(target)):
            self._reload_target(target)

            records = self._records_for(target)
            entries = [record.content for record in records]
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}

            if len(matches) > 1:
                # If all matches are identical, only auto-resolve when their
                # structured classes are also identical. Same content with
                # different classes is ambiguous in the structured model.
                unique_texts = set(e for _, e in matches)
                if len(unique_texts) > 1:
                    previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                    return {
                        "success": False,
                        "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                        "matches": previews,
                    }
                unique_classes = {records[i].memory_class for i, _ in matches}
                if len(unique_classes) > 1:
                    return {
                        "success": False,
                        "error": (
                            f"Multiple structured entries matched '{old_text}' with different classes. "
                            "Be more specific."
                        ),
                        "matches": [records[i].to_dict() for i, _ in matches],
                    }
                # All identical text/class duplicates -- safe to remove just the first

            idx = matches[0][0]
            records = self._records_for(target)
            removed_record = records.pop(idx)
            self._set_records(target, records)
            self.save_to_disk(target)

        result = self._success_response(target, "Entry removed.")
        result["removed_content"] = removed_record.content
        result["removed_entry"] = removed_record.to_dict()
        result["changed"] = True
        return result

    def format_for_system_prompt(self, target: str) -> Optional[str]:
        """
        Return the frozen snapshot for system prompt injection.

        This returns the state captured at load_from_disk() time, NOT the live
        state. Mid-session writes do not affect this. This keeps the system
        prompt stable across all turns, preserving the prefix cache.

        Returns None if the snapshot is empty (no entries at load time).
        """
        block = self._system_prompt_snapshot.get(target, "")
        return block if block else None

    # -- Internal helpers --

    def _success_response(self, target: str, message: str = None) -> Dict[str, Any]:
        entries = self._entries_for(target)
        current = self._char_count(target)
        limit = self._char_limit(target)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

        resp = {
            "success": True,
            "target": target,
            "entries": entries,
            "structured_entries": self._structured_entries_for(target),
            "usage": f"{pct}% — {current:,}/{limit:,} chars",
            "entry_count": len(entries),
        }
        if message:
            resp["message"] = message
        return resp

    def _render_block(self, target: str, entries: List[str]) -> str:
        """Render a system prompt block with header and usage indicator."""
        if not entries:
            return ""

        limit = self._char_limit(target)
        content = ENTRY_DELIMITER.join(entries)
        current = len(content)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

        if target == "user":
            header = f"USER PROFILE (who the user is) [{pct}% — {current:,}/{limit:,} chars]"
        else:
            header = f"MEMORY (your personal notes) [{pct}% — {current:,}/{limit:,} chars]"

        separator = "═" * 46
        return f"{separator}\n{header}\n{separator}\n{content}"

    @staticmethod
    def _read_records(path: Path) -> List[MemoryRecord]:
        """Read a memory file and split into structured records.

        No file locking needed: _write_records uses atomic rename, so readers
        always see either the previous complete file or the new complete file.
        """
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, IOError):
            return []

        if not raw.strip():
            return []

        entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
        return [_deserialize_record(e) for e in entries if e]

    @staticmethod
    def _write_records(path: Path, records: List[MemoryRecord]):
        """Write structured records to a memory file using atomic temp-file + rename.

        Previous implementation used open("w") + flock, but "w" truncates the
        file *before* the lock is acquired, creating a race window where
        concurrent readers see an empty file. Atomic rename avoids this:
        readers always see either the old complete file or the new one.
        """
        content = ENTRY_DELIMITER.join(_serialize_record(record) for record in records) if records else ""
        try:
            # Write to temp file in same directory (same filesystem for atomic rename)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp", prefix=".mem_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, str(path))  # Atomic on same filesystem
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except (OSError, IOError) as e:
            raise RuntimeError(f"Failed to write memory file {path}: {e}")


# Backwards-compatible aliases for older callers/tests.
MemoryStore._read_file = staticmethod(lambda path: [record.content for record in MemoryStore._read_records(path)])
MemoryStore._write_file = staticmethod(lambda path, entries: MemoryStore._write_records(path, [MemoryRecord(content=entry) for entry in entries]))


def memory_tool(
    action: str,
    target: str = "memory",
    content: str = None,
    old_text: str = None,
    memory_class: Optional[str] = None,
    store: Optional[MemoryStore] = None,
) -> str:
    """
    Single entry point for the memory tool. Dispatches to MemoryStore methods.

    Returns JSON string with results.
    """
    if store is None:
        return tool_error("Memory is not available. It may be disabled in config or this environment.", success=False)

    if target not in ("memory", "user"):
        return tool_error(f"Invalid target '{target}'. Use 'memory' or 'user'.", success=False)

    if action == "add":
        if not content:
            return tool_error("Content is required for 'add' action.", success=False)
        result = store.add(target, content, entry_class=memory_class)

    elif action == "replace":
        if not old_text:
            return tool_error("old_text is required for 'replace' action.", success=False)
        if not content:
            return tool_error("content is required for 'replace' action.", success=False)
        result = store.replace(target, old_text, content, entry_class=memory_class)

    elif action == "remove":
        if not old_text:
            return tool_error("old_text is required for 'remove' action.", success=False)
        result = store.remove(target, old_text)

    else:
        return tool_error(f"Unknown action '{action}'. Use: add, replace, remove", success=False)

    return json.dumps(result, ensure_ascii=False)


def check_memory_requirements() -> bool:
    """Memory tool has no external requirements -- always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Save durable information to persistent memory that survives across sessions. "
        "Memory is injected into future turns, so keep it compact and focused on facts "
        "that will still matter later.\n\n"
        "WHEN TO SAVE (do this proactively, don't wait to be asked):\n"
        "- User corrects you or says 'remember this' / 'don't do that again'\n"
        "- User shares a preference, habit, or personal detail (name, role, timezone, coding style)\n"
        "- You discover something about the environment (OS, installed tools, project structure)\n"
        "- You learn a convention, API quirk, or workflow specific to this user's setup\n"
        "- You identify a stable fact that will be useful again in future sessions\n\n"
        "PRIORITY: User preferences and corrections > environment facts > procedural knowledge. "
        "The most valuable memory prevents the user from having to repeat themselves.\n\n"
        "Do NOT save task progress, session outcomes, completed-work logs, or temporary TODO "
        "state to memory; use session_search to recall those from past transcripts.\n"
        "If you've discovered a new way to do something, solved a problem that could be "
        "necessary later, save it as a skill with the skill tool.\n\n"
        "TWO TARGETS:\n"
        "- 'user': who the user is -- name, role, preferences, communication style, pet peeves\n"
        "- 'memory': your notes -- environment facts, project conventions, tool quirks, lessons learned\n\n"
        "ACTIONS: add (new entry), replace (update existing -- old_text identifies it), "
        "remove (delete -- old_text identifies it).\n\n"
        "SKIP: trivial/obvious info, things easily re-discovered, raw data dumps, and temporary task state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "The action to perform."
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which memory store: 'memory' for personal notes, 'user' for user profile."
            },
            "content": {
                "type": "string",
                "description": "The entry content. Required for 'add' and 'replace'."
            },
            "memory_class": {
                "type": "string",
                "description": "Optional structured class for the entry. Use classes like preference/identity/profile/communication for target='user', and environment/tooling/workflow/project/convention/correction for target='memory'. Defaults to 'other'."
            },
            "old_text": {
                "type": "string",
                "description": "Short unique substring identifying the entry to replace or remove."
            },
        },
        "required": ["action", "target"],
    },
}


# --- Registry ---
from tools.registry import registry, tool_error

registry.register(
    name="memory",
    toolset="memory",
    schema=MEMORY_SCHEMA,
    handler=lambda args, **kw: memory_tool(
        action=args.get("action", ""),
        target=args.get("target", "memory"),
        content=args.get("content"),
        old_text=args.get("old_text"),
        memory_class=args.get("memory_class"),
        store=kw.get("store")),
    check_fn=check_memory_requirements,
    emoji="🧠",
)




