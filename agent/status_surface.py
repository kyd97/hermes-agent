"""Unified task/run status surface helpers for Hermes.

Combines session activity, todo state, delegation outcomes, and cron jobs into
one compact structure that can be reused by tools and gateway status surfaces.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import json


def extract_todos_from_history(history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recover the most recent todo list from conversation history."""
    for msg in reversed(history or []):
        if msg.get("role") != "tool":
            continue
        content = msg.get("content", "")
        if '"todos"' not in content:
            continue
        try:
            data = json.loads(content)
        except (TypeError, json.JSONDecodeError):
            continue
        todos = data.get("todos")
        if isinstance(todos, list):
            return todos
    return []


def summarize_todos(todos: List[Dict[str, Any]]) -> Dict[str, Any]:
    normalized: List[Dict[str, Any]] = []
    counts = {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0}
    for item in todos or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "pending")).strip().lower()
        if status not in counts:
            status = "pending"
        normalized_item: Dict[str, Any] = {
            "id": str(item.get("id", "")).strip() or "?",
            "content": str(item.get("content", "")).strip() or "(no description)",
            "status": status,
        }
        for field in ("owner", "dependencies", "artifact_path", "run_id", "priority"):
            if field not in item:
                continue
            value = item.get(field)
            if field == "dependencies":
                if isinstance(value, list):
                    deps = [str(dep).strip() for dep in value if str(dep).strip()]
                    if deps:
                        normalized_item[field] = deps
                continue
            if value not in (None, ""):
                normalized_item[field] = str(value).strip() if field != "priority" else str(value).strip().lower()
        normalized.append(normalized_item)
        counts[status] += 1
    return {
        "items": normalized,
        "summary": {
            "total": len(normalized),
            **counts,
        },
    }


def summarize_delegate_history(history: List[Dict[str, Any]], limit: int = 5) -> Dict[str, Any]:
    entries = [entry for entry in (history or []) if isinstance(entry, dict)]
    recent = entries[-limit:] if limit > 0 else entries[:]
    counts = {
        "total": len(entries),
        "completed": 0,
        "failed": 0,
        "interrupted": 0,
        "error": 0,
    }
    for entry in entries:
        status = str(entry.get("status", "")).strip().lower()
        if status in counts:
            counts[status] += 1
    return {"summary": counts, "recent": recent}


def summarize_cron_jobs(limit: int = 5) -> Dict[str, Any]:
    try:
        from cron.jobs import list_jobs
        jobs = list_jobs(include_disabled=True)
    except Exception:
        return {"summary": {"total": 0, "enabled": 0, "paused": 0}, "jobs": []}

    formatted = []
    enabled = 0
    paused = 0
    for job in jobs:
        job_enabled = bool(job.get("enabled", True))
        if job_enabled:
            enabled += 1
        else:
            paused += 1
        formatted.append(
            {
                "id": job.get("id"),
                "name": job.get("name"),
                "state": job.get("state", "scheduled" if job_enabled else "paused"),
                "schedule": job.get("schedule_display"),
                "next_run_at": job.get("next_run_at"),
                "last_status": job.get("last_status"),
                "enabled": job_enabled,
            }
        )
    return {
        "summary": {"total": len(formatted), "enabled": enabled, "paused": paused},
        "jobs": formatted[:limit] if limit > 0 else formatted,
    }


def build_status_surface(
    *,
    agent=None,
    history: Optional[List[Dict[str, Any]]] = None,
    session_id: Optional[str] = None,
    session_title: Optional[str] = None,
    agent_running: bool = False,
    include_cron_jobs: int = 5,
) -> Dict[str, Any]:
    """Build a unified status payload for the current session."""
    todos = []
    activity = None
    delegate_history: List[Dict[str, Any]] = []
    model = None
    provider = None
    if agent is not None:
        try:
            activity = agent.get_activity_summary()
        except Exception:
            activity = None
        model = getattr(agent, "model", None)
        provider = getattr(agent, "provider", None)
        todo_store = getattr(agent, "_todo_store", None)
        if todo_store is not None:
            try:
                todos = todo_store.read()
            except Exception:
                todos = []
        delegate_history = list(getattr(agent, "_delegate_history", []) or [])
    if not todos and history:
        todos = extract_todos_from_history(history)

    return {
        "session": {
            "session_id": session_id,
            "title": session_title,
            "agent_running": agent_running,
            "model": model,
            "provider": provider,
        },
        "activity": activity,
        "todos": summarize_todos(todos),
        "delegation": summarize_delegate_history(delegate_history),
        "cron": summarize_cron_jobs(limit=include_cron_jobs),
    }
