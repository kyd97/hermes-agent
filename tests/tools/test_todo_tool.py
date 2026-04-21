"""Tests for the todo tool module."""

import json

from tools.todo_tool import TODO_SCHEMA, TodoStore, todo_tool


class TestWriteAndRead:
    def test_write_replaces_list(self):
        store = TodoStore()
        items = [
            {"id": "1", "content": "First task", "status": "pending"},
            {"id": "2", "content": "Second task", "status": "in_progress"},
        ]
        result = store.write(items)
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["status"] == "in_progress"

    def test_read_returns_copy(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "Task", "status": "pending"}])
        items = store.read()
        items[0]["content"] = "MUTATED"
        assert store.read()[0]["content"] == "Task"

    def test_write_deduplicates_duplicate_ids(self):
        store = TodoStore()
        result = store.write([
            {"id": "1", "content": "First version", "status": "pending"},
            {"id": "2", "content": "Other task", "status": "pending"},
            {"id": "1", "content": "Latest version", "status": "in_progress"},
        ])
        assert result == [
            {"id": "2", "content": "Other task", "status": "pending"},
            {"id": "1", "content": "Latest version", "status": "in_progress"},
        ]


class TestHasItems:
    def test_empty_store(self):
        store = TodoStore()
        assert store.has_items() is False

    def test_non_empty_store(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "x", "status": "pending"}])
        assert store.has_items() is True


class TestFormatForInjection:
    def test_empty_returns_none(self):
        store = TodoStore()
        assert store.format_for_injection() is None

    def test_non_empty_has_markers(self):
        store = TodoStore()
        store.write([
            {"id": "1", "content": "Do thing", "status": "completed"},
            {"id": "2", "content": "Next", "status": "pending"},
            {"id": "3", "content": "Working", "status": "in_progress"},
        ])
        text = store.format_for_injection()
        # Completed items are filtered out of injection
        assert "[x]" not in text
        assert "Do thing" not in text
        # Active items are included
        assert "[ ]" in text
        assert "[>]" in text
        assert "Next" in text
        assert "Working" in text
        assert "context compression" in text.lower()


class TestMergeMode:
    def test_update_existing_by_id(self):
        store = TodoStore()
        store.write([
            {"id": "1", "content": "Original", "status": "pending"},
        ])
        store.write(
            [{"id": "1", "status": "completed"}],
            merge=True,
        )
        items = store.read()
        assert len(items) == 1
        assert items[0]["status"] == "completed"
        assert items[0]["content"] == "Original"

    def test_merge_appends_new(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "First", "status": "pending"}])
        store.write(
            [{"id": "2", "content": "Second", "status": "pending"}],
            merge=True,
        )
        items = store.read()
        assert len(items) == 2

    def test_write_preserves_orchestration_metadata(self):
        store = TodoStore()
        result = store.write([
            {
                "id": "1",
                "content": "Ship feature",
                "status": "pending",
                "owner": "delegate:claude",
                "dependencies": ["setup", "tests"],
                "artifact_path": "/tmp/report.md",
                "run_id": "run-123",
                "priority": "high",
            }
        ])
        assert result[0]["owner"] == "delegate:claude"
        assert result[0]["dependencies"] == ["setup", "tests"]
        assert result[0]["artifact_path"] == "/tmp/report.md"
        assert result[0]["run_id"] == "run-123"
        assert result[0]["priority"] == "high"

    def test_merge_updates_orchestration_metadata_by_id(self):
        store = TodoStore()
        store.write([
            {
                "id": "1",
                "content": "Ship feature",
                "status": "pending",
                "owner": "delegate:claude",
                "dependencies": ["setup"],
                "priority": "low",
            }
        ])
        store.write([
            {
                "id": "1",
                "run_id": "run-999",
                "artifact_path": "/tmp/out.json",
                "dependencies": ["setup", "tests"],
                "priority": "urgent",
            }
        ], merge=True)
        items = store.read()
        assert items[0]["owner"] == "delegate:claude"
        assert items[0]["run_id"] == "run-999"
        assert items[0]["artifact_path"] == "/tmp/out.json"
        assert items[0]["dependencies"] == ["setup", "tests"]
        assert items[0]["priority"] == "urgent"

    def test_merge_can_clear_orchestration_metadata(self):
        store = TodoStore()
        store.write([
            {
                "id": "1",
                "content": "Ship feature",
                "status": "pending",
                "owner": "delegate:claude",
                "dependencies": ["setup"],
                "artifact_path": "/tmp/out.json",
                "run_id": "run-123",
                "priority": "high",
            }
        ])
        store.write([
            {
                "id": "1",
                "dependencies": [],
                "artifact_path": "",
                "run_id": None,
                "priority": "bogus",
            }
        ], merge=True)
        items = store.read()
        assert "dependencies" not in items[0]
        assert "artifact_path" not in items[0]
        assert "run_id" not in items[0]
        assert "priority" not in items[0]
        assert items[0]["owner"] == "delegate:claude"


class TestSchema:
    def test_todo_schema_exposes_orchestration_metadata_fields(self):
        item_props = TODO_SCHEMA["parameters"]["properties"]["todos"]["items"]["properties"]
        assert {branch["type"] for branch in item_props["owner"]["anyOf"]} == {"string", "null"}
        assert {branch["type"] for branch in item_props["dependencies"]["anyOf"]} == {"array", "null"}
        assert {branch["type"] for branch in item_props["artifact_path"]["anyOf"]} == {"string", "null"}
        assert {branch["type"] for branch in item_props["run_id"]["anyOf"]} == {"string", "null"}
        assert item_props["priority"]["anyOf"][0]["enum"] == ["low", "medium", "high", "urgent"]

    def test_todo_schema_allows_partial_merge_items(self):
        item_schema = TODO_SCHEMA["parameters"]["properties"]["todos"]["items"]
        assert item_schema["required"] == ["id"]
        assert {branch["type"] for branch in item_schema["properties"]["priority"]["anyOf"]} == {"string", "null"}


class TestTodoToolFunction:
    def test_read_mode(self):
        store = TodoStore()
        store.write([{"id": "1", "content": "Task", "status": "pending"}])
        result = json.loads(todo_tool(store=store))
        assert result["summary"]["total"] == 1
        assert result["summary"]["pending"] == 1

    def test_write_mode(self):
        store = TodoStore()
        result = json.loads(todo_tool(
            todos=[{"id": "1", "content": "New", "status": "in_progress"}],
            store=store,
        ))
        assert result["summary"]["in_progress"] == 1

    def test_no_store_returns_error(self):
        result = json.loads(todo_tool())
        assert "error" in result
