"""Tests for tools/document_ingest.py."""

from tools.document_ingest import ingest_document


def test_ingest_document_reads_text_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world")

    result = ingest_document(str(path))

    assert result["success"] is True
    assert result["summary"] == "hello world"
    assert result["extracted_text"] == "hello world"


def test_ingest_document_returns_failure_when_no_text_can_be_extracted(tmp_path):
    path = tmp_path / "legacy.doc"
    path.write_bytes(b"\x00\x01\x02\x03")

    result = ingest_document(str(path))

    assert result["success"] is False
    assert result["error"] == "No extractable text found."
