"""Tests for cron delegated execution mode and fan-out payload building."""

import json
from types import SimpleNamespace

import pytest

from cron.scheduler import _build_delegate_payload, _run_job_via_delegate, tick


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    import cron.jobs as jobs_mod
    import cron.scheduler as sched_mod

    hermes_home = tmp_path / ".hermes"
    cron_dir = hermes_home / "cron"
    cron_dir.mkdir(parents=True)
    (cron_dir / "output").mkdir()

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(jobs_mod, "HERMES_DIR", hermes_home)
    monkeypatch.setattr(jobs_mod, "CRON_DIR", cron_dir)
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", cron_dir / "jobs.json")
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", cron_dir / "output")
    monkeypatch.setattr(sched_mod, "_LOCK_DIR", cron_dir)
    monkeypatch.setattr(sched_mod, "_LOCK_FILE", cron_dir / ".tick.lock")
    return hermes_home


class TestBuildDelegatePayload:
    def test_fanout_payload_merges_shared_context_and_defaults(self):
        job = {
            "prompt": "Inspect the environment and report notable issues.",
            "delegate": {
                "context": "Shared context from the cron config.",
                "toolsets": ["terminal", "file"],
                "tasks": [
                    {"goal": "Check deployment status"},
                    {"goal": "Summarize errors", "context": "Look at the latest logs."},
                ],
            },
        }

        payload = _build_delegate_payload(job, "Instruction body")

        assert len(payload["tasks"]) == 2
        assert payload["tasks"][0]["toolsets"] == ["terminal", "file"]
        assert "CRON JOB INSTRUCTION:\nInstruction body" in payload["tasks"][0]["context"]
        assert "Shared context from the cron config." in payload["tasks"][0]["context"]
        assert payload["tasks"][1]["context"].endswith("Look at the latest logs.")

    def test_single_delegate_payload_falls_back_to_prompt_goal(self):
        job = {
            "prompt": "Generate the weekly rollout summary.",
            "delegate": {"toolsets": ["file"]},
        }

        payload = _build_delegate_payload(job, "Instruction body")

        assert payload["goal"] == "Generate the weekly rollout summary."
        assert payload["toolsets"] == ["file"]
        assert "Instruction body" in payload["context"]


class TestRunJobViaDelegate:
    def test_renders_fanout_results(self, monkeypatch):
        calls = []

        def fake_delegate_task(*, parent_agent=None, **kwargs):
            calls.append({"parent_agent": parent_agent, **kwargs})
            return json.dumps(
                {
                    "results": [
                        {"task_index": 0, "status": "completed", "summary": "Deployment is healthy."},
                        {"task_index": 1, "status": "failed", "error": "Log source unavailable."},
                    ]
                }
            )

        monkeypatch.setattr("tools.delegate_tool.delegate_task", fake_delegate_task)

        job = {
            "prompt": "Inspect production health.",
            "delegate": {
                "tasks": [
                    {"goal": "Check deployment status"},
                    {"goal": "Summarize recent errors"},
                ]
            },
        }
        controller = SimpleNamespace()

        success, final_response, error = _run_job_via_delegate(job, controller, "Instruction body")

        assert success is True
        assert error is None
        assert "Delegated cron run finished: 1/2 task(s) completed." in final_response
        assert "Check deployment status" in final_response
        assert "Deployment is healthy." in final_response
        assert "Error: Log source unavailable." in final_response
        assert calls[0]["parent_agent"] is controller
        assert calls[0]["tasks"][0]["goal"] == "Check deployment status"
        assert "Instruction body" in calls[0]["tasks"][0]["context"]

    def test_returns_error_when_delegate_tool_errors(self, monkeypatch):
        def fake_delegate_task(*, parent_agent=None, **kwargs):
            return json.dumps({"error": "delegation failed"})

        monkeypatch.setattr("tools.delegate_tool.delegate_task", fake_delegate_task)

        success, final_response, error = _run_job_via_delegate(
            {"prompt": "Do the thing.", "delegate": {"goal": "Do the thing."}},
            SimpleNamespace(),
            "Instruction body",
        )

        assert success is False
        assert final_response == ""
        assert error == "delegation failed"


class TestDelegateTickPersistence:
    def test_delegate_mode_job_persists_execution_metadata(self, cron_env, monkeypatch):
        from cron.jobs import create_job, get_job, trigger_job

        job = create_job(
            prompt="Inspect the fleet.",
            schedule="every 1h",
            execution_mode="delegate",
            delegate={"goal": "Inspect the fleet."},
        )
        trigger_job(job["id"])

        monkeypatch.setattr(
            "cron.scheduler.run_job",
            lambda _job: (True, "# output", "Delegated cron run finished: 1/1 task(s) completed.", None),
        )
        monkeypatch.setattr("cron.scheduler._deliver_result", lambda *args, **kwargs: None)

        executed = tick(verbose=False)
        stored = get_job(job["id"])

        assert executed == 1
        assert stored["execution_mode"] == "delegate"
        assert stored["last_status"] == "ok"
        assert stored["last_run_at"] is not None
        assert stored["last_delivery_error"] is None
