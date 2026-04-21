"""Tests for unified work status surface helpers/tool."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from agent.status_surface import build_status_surface, extract_todos_from_history
from tools.work_status_tool import work_status_tool


def test_extract_todos_from_history_uses_latest_todo_response():
    history = [
        {"role": "tool", "content": json.dumps({"todos": [{"id": "1", "content": "old", "status": "pending"}]})},
        {"role": "tool", "content": json.dumps({"todos": [{"id": "2", "content": "new", "status": "in_progress"}]})},
    ]
    assert extract_todos_from_history(history) == [{"id": "2", "content": "new", "status": "in_progress"}]


def test_build_status_surface_includes_todos_delegation_and_cron_summary():
    agent = SimpleNamespace(
        session_id="sess-1",
        model="gpt-5.4",
        provider="openai-codex",
        _todo_store=SimpleNamespace(read=lambda: [{
            "id": "t1",
            "content": "Do it",
            "status": "in_progress",
            "owner": "delegate:claude",
            "dependencies": ["setup"],
            "artifact_path": "/tmp/out.md",
            "run_id": "run-1",
            "priority": "high",
        }]),
        _delegate_history=[{"label": "task", "status": "completed", "summary": "done"}],
        get_activity_summary=lambda: {"current_tool": "terminal", "api_call_count": 2},
    )
    with patch("cron.jobs.list_jobs", return_value=[]):
        payload = build_status_surface(agent=agent, session_id="sess-1", agent_running=True)
    assert payload["todos"]["summary"]["in_progress"] == 1
    assert payload["todos"]["items"][0]["owner"] == "delegate:claude"
    assert payload["todos"]["items"][0]["dependencies"] == ["setup"]
    assert payload["todos"]["items"][0]["artifact_path"] == "/tmp/out.md"
    assert payload["todos"]["items"][0]["run_id"] == "run-1"
    assert payload["todos"]["items"][0]["priority"] == "high"
    assert payload["delegation"]["summary"]["completed"] == 1
    assert payload["cron"]["summary"]["total"] == 0
    assert payload["activity"]["current_tool"] == "terminal"


def test_work_status_tool_returns_success_payload():
    agent = SimpleNamespace(
        session_id="sess-1",
        model="gpt-5.4",
        provider="openai-codex",
        _todo_store=SimpleNamespace(read=lambda: []),
        _delegate_history=[],
        get_activity_summary=lambda: {"current_tool": None, "api_call_count": 0},
    )
    with patch("cron.jobs.list_jobs", return_value=[]):
        result = json.loads(work_status_tool(agent=agent))
    assert result["success"] is True
    assert result["session"]["session_id"] == "sess-1"
    assert "todos" in result
    assert "delegation" in result
    assert "cron" in result
