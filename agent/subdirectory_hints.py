"""Progressive subdirectory hint discovery.

As the agent navigates into subdirectories via tool calls (read_file, terminal,
search_files, etc.), this module discovers and loads project context files
(AGENTS.md, CLAUDE.md, .cursorrules) from those directories.  Discovered hints
are appended to the tool result so the model gets relevant context at the moment
it starts working in a new area of the codebase.

This complements the startup context loading in ``prompt_builder.py`` which only
loads from the CWD.  Subdirectory hints are discovered lazily and injected into
the conversation without modifying the system prompt (preserving prompt caching).

Inspired by Block/goose's SubdirectoryHintTracker.
"""

import logging
import os
import shlex
from pathlib import Path
from typing import Dict, Any, Optional, Set

from agent.prompt_builder import _scan_context_content

_INSTRUCTION_PACK_DIRS = (
    (".hermes", "instructions"),
    ("HERMES.d",),
)
_INSTRUCTION_PACK_EXTENSIONS = {".md", ".mdc", ".txt"}

logger = logging.getLogger(__name__)

# Context files to look for in subdirectories, in priority order.
# Same filenames as prompt_builder.py but we load ALL found (not first-wins)
# since different subdirectories may use different conventions.
_HINT_FILENAMES = [
    "AGENTS.md", "agents.md",
    "CLAUDE.md", "claude.md",
    ".cursorrules",
]

# Maximum chars per hint file to prevent context bloat
_MAX_HINT_CHARS = 8_000

# Tool argument keys that typically contain file paths
_PATH_ARG_KEYS = {"path", "file_path", "workdir"}

# Tools that take shell commands where we should extract paths
_COMMAND_TOOLS = {"terminal"}

# How many parent directories to walk up when looking for hints.
# Prevents scanning all the way to / for deeply nested paths.
_MAX_ANCESTOR_WALK = 5

class SubdirectoryHintTracker:
    """Track which directories the agent visits and load hints on first access.

    Usage::

        tracker = SubdirectoryHintTracker(working_dir="/path/to/project")

        # After each tool call:
        hints = tracker.check_tool_call("read_file", {"path": "backend/src/main.py"})
        if hints:
            tool_result += hints  # append to the tool result string
    """

    def __init__(self, working_dir: Optional[str] = None):
        self.working_dir = Path(working_dir or os.getcwd()).resolve()
        self._loaded_dirs: Set[Path] = set()
        # Pre-mark the working dir as loaded (startup context handles it)
        self._loaded_dirs.add(self.working_dir)

    def check_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
    ) -> Optional[str]:
        """Check tool call arguments for new directories and load any hint files.

        Returns formatted hint text to append to the tool result, or None.
        """
        dirs = self._extract_directories(tool_name, tool_args)
        if not dirs:
            return None

        all_hints = []
        for d in dirs:
            hints = self._load_hints_for_directory(d)
            if hints:
                all_hints.append(hints)

        if not all_hints:
            return None

        return "\n\n" + "\n\n".join(all_hints)

    def _extract_directories(
        self, tool_name: str, args: Dict[str, Any]
    ) -> list:
        """Extract directory paths from tool call arguments."""
        candidates: Set[Path] = set()

        # Direct path arguments
        for key in _PATH_ARG_KEYS:
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                self._add_path_candidate(val, candidates)

        # Shell commands — extract path-like tokens
        if tool_name in _COMMAND_TOOLS:
            cmd = args.get("command", "")
            if isinstance(cmd, str):
                self._extract_paths_from_command(cmd, candidates)

        return list(candidates)

    def _add_path_candidate(self, raw_path: str, candidates: Set[Path]):
        """Resolve a raw path and add its directory + ancestors to candidates.

        Walks up from the resolved directory toward the filesystem root,
        stopping at the first directory already in ``_loaded_dirs`` (or after
        ``_MAX_ANCESTOR_WALK`` levels).  This ensures that reading
        ``project/src/main.py`` discovers ``project/AGENTS.md`` even when
        ``project/src/`` has no hint files of its own.
        """
        try:
            p = Path(raw_path).expanduser()
            if not p.is_absolute():
                p = self.working_dir / p
            p = p.resolve()
            # Use parent if it's a file path (has extension or doesn't exist as dir)
            if p.suffix or (p.exists() and p.is_file()):
                p = p.parent
            # Walk up ancestors — stop at already-loaded or root
            for _ in range(_MAX_ANCESTOR_WALK):
                if p in self._loaded_dirs:
                    break
                if self._is_valid_subdir(p):
                    candidates.add(p)
                parent = p.parent
                if parent == p:
                    break  # filesystem root
                p = parent
        except (OSError, ValueError):
            pass

    def _extract_paths_from_command(self, cmd: str, candidates: Set[Path]):
        """Extract path-like tokens from a shell command string."""
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()

        for token in tokens:
            # Skip flags
            if token.startswith("-"):
                continue
            # Must look like a path (contains / or .)
            if "/" not in token and "." not in token:
                continue
            # Skip URLs
            if token.startswith(("http://", "https://", "git@")):
                continue
            self._add_path_candidate(token, candidates)

    def _is_valid_subdir(self, path: Path) -> bool:
        """Check if path is a valid directory to scan for hints."""
        try:
            if not path.is_dir():
                return False
        except OSError:
            return False
        if path in self._loaded_dirs:
            return False
        return True

    def _load_hints_for_directory(self, directory: Path) -> Optional[str]:
        """Load hint files from a directory. Returns formatted text or None."""
        self._loaded_dirs.add(directory)

        sections = []
        hint_section = self._load_single_hint_file(directory)
        if hint_section:
            sections.append(hint_section)
        instruction_section = self._load_instruction_packs(directory)
        if instruction_section:
            sections.append(instruction_section)

        if not sections:
            return None

        logger.debug("Loaded subdirectory hints from %s", directory)
        return "\n\n".join(sections)

    def _load_single_hint_file(self, directory: Path) -> Optional[str]:
        """Load the first matching classic hint file from a directory."""
        for filename in _HINT_FILENAMES:
            hint_path = directory / filename
            try:
                if not hint_path.is_file():
                    continue
            except OSError:
                continue
            try:
                content = hint_path.read_text(encoding="utf-8").strip()
                if not content:
                    continue
                content = _scan_context_content(content, filename)
                if len(content) > _MAX_HINT_CHARS:
                    content = (
                        content[:_MAX_HINT_CHARS]
                        + f"\n\n[...truncated {filename}: {len(content):,} chars total]"
                    )
                rel_path = self._display_path(hint_path)
                return f"[Subdirectory context discovered: {rel_path}]\n{content}"
            except Exception as exc:
                logger.debug("Could not read %s: %s", hint_path, exc)
        return None

    def _load_instruction_packs(self, directory: Path) -> Optional[str]:
        """Load modular instruction packs from a visited directory."""
        rendered_packs = []
        for pack_dir_parts in _INSTRUCTION_PACK_DIRS:
            pack_dir = directory.joinpath(*pack_dir_parts)
            try:
                if not pack_dir.is_dir():
                    continue
            except OSError:
                continue
            try:
                pack_files = sorted(
                    [
                        child for child in pack_dir.iterdir()
                        if child.is_file() and child.suffix.lower() in _INSTRUCTION_PACK_EXTENSIONS
                    ],
                    key=lambda p: p.name,
                )
            except Exception as exc:
                logger.debug("Could not read instruction packs in %s: %s", pack_dir, exc)
                continue

            for pack_file in pack_files:
                try:
                    content = pack_file.read_text(encoding="utf-8").strip()
                    if not content:
                        continue
                    rel_path = self._display_path(pack_file)
                    content = _scan_context_content(content, rel_path)
                    rendered = f"### {rel_path}\n{content}"
                    if len(rendered) > _MAX_HINT_CHARS:
                        rendered = (
                            rendered[:_MAX_HINT_CHARS]
                            + f"\n\n[...truncated {pack_file.name}: {len(rendered):,} chars total]"
                        )
                    rendered_packs.append(rendered)
                except Exception as exc:
                    logger.debug("Could not read instruction pack %s: %s", pack_file, exc)

        if not rendered_packs:
            return None
        return "[Subdirectory context discovered: Project instruction packs]\n" + "\n\n".join(rendered_packs)

    def _display_path(self, path: Path) -> str:
        """Best-effort relative path for display."""
        rel_path = str(path)
        try:
            rel_path = str(path.relative_to(self.working_dir))
        except ValueError:
            try:
                rel_path = str(path.relative_to(Path.home()))
                rel_path = "~/" + rel_path
            except ValueError:
                pass
        return rel_path
