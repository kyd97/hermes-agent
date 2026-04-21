#!/usr/bin/env python3
"""Work status tool — unified task and run status surface for the current session."""

import json
from typing import Optional

from agent.status_surface import build_status_surface
from tools.registry import registry, tool_error


def work_status_tool(include_cron_jobs: int = 5, *, agent=None) -> str:
    if agent is None:
        return tool_error("work_status requires an active agent context.", success=False)
    payload = build_status_surface(
        agent=agent,
        session_id=getattr(agent, "session_id", None),
        agent_running=True,
        include_cron_jobs=include_cron_jobs,
    )
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


WORK_STATUS_SCHEMA = {
    "name": "work_status",
    "description": (
        "Get a unified status surface for the current session. Returns current run/activity, "
        "task list, recent delegation results, and cron job summary. Use when you need to inspect "
        "what Hermes is actively doing or what work remains."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "include_cron_jobs": {
                "type": "integer",
                "description": "Maximum number of cron jobs to include in the response (default 5).",
                "default": 5,
            }
        },
        "required": [],
    },
}


registry.register(
    name="work_status",
    toolset="todo",
    schema=WORK_STATUS_SCHEMA,
    handler=lambda args, **kw: work_status_tool(
        include_cron_jobs=args.get("include_cron_jobs", 5),
        agent=kw.get("agent"),
    ),
    check_fn=lambda: True,
    emoji="📊",
)
