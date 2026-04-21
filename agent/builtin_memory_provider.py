"""Built-in memory provider backed by MemoryStore.

Wraps Hermes' file-backed MEMORY.md / USER.md store in the MemoryProvider
interface so built-in memory participates in the same orchestration path as
external memory plugins.
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider
from tools.memory_tool import MemoryStore


class BuiltinMemoryProvider(MemoryProvider):
    """Expose file-backed built-in memory through the MemoryProvider API."""

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        *,
        memory_enabled: bool = True,
        user_profile_enabled: bool = True,
    ) -> None:
        self._memory_store = memory_store or MemoryStore()
        self._memory_enabled = bool(memory_enabled)
        self._user_profile_enabled = bool(user_profile_enabled)

    @property
    def name(self) -> str:
        return "builtin"

    def is_available(self) -> bool:
        return self._memory_store is not None and (
            self._memory_enabled or self._user_profile_enabled
        )

    def initialize(self, session_id: str, **kwargs) -> None:
        # Refresh the frozen snapshot for this session. MemoryStore itself keeps
        # mid-session writes out of the prompt cache, so reloading here is safe.
        self._memory_store.load_from_disk()

    def system_prompt_block(self) -> str:
        blocks: List[str] = []
        if self._memory_enabled:
            memory_block = self._memory_store.format_for_system_prompt("memory")
            if memory_block:
                blocks.append(memory_block)
        if self._user_profile_enabled:
            user_block = self._memory_store.format_for_system_prompt("user")
            if user_block:
                blocks.append(user_block)
        return "\n\n".join(blocks)

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        # The built-in memory tool already exists on the normal Hermes tool
        # surface. This provider only unifies prompt/lifecycle orchestration.
        return []
