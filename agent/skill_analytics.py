"""Helpers for recording skill analytics events."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from hermes_state import SessionDB

logger = logging.getLogger(__name__)


def _get_session_context() -> Dict[str, Optional[str]]:
    try:
        from gateway.session_context import get_session_env
    except Exception:
        import os
        return {
            "source": os.getenv("HERMES_SESSION_PLATFORM") or os.getenv("HERMES_PLATFORM") or "cli",
            "session_key": os.getenv("HERMES_SESSION_KEY") or None,
        }

    source = get_session_env("HERMES_SESSION_PLATFORM") or get_session_env("HERMES_PLATFORM") or "cli"
    session_key = get_session_env("HERMES_SESSION_KEY") or None
    return {"source": source, "session_key": session_key}


def log_skill_event(
    *,
    skill_name: str,
    event_type: str,
    session_id: str | None = None,
    trigger: str | None = None,
    parent_skill_name: str | None = None,
    success: bool | None = None,
    metadata: Dict[str, Any] | None = None,
) -> None:
    """Best-effort logging wrapper around SessionDB.log_skill_event()."""
    if not skill_name or not event_type:
        return

    ctx = _get_session_context()
    try:
        db = SessionDB()
        try:
            db.log_skill_event(
                skill_name=skill_name,
                event_type=event_type,
                session_id=session_id,
                session_key=ctx.get("session_key"),
                source=ctx.get("source"),
                trigger=trigger,
                parent_skill_name=parent_skill_name,
                success=success,
                metadata=metadata,
            )
        finally:
            db.close()
    except Exception:
        logger.debug("Failed to log skill analytics event", exc_info=True)
