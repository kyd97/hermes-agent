"""Tests for gateway-side document ingest and enrichment."""

from unittest.mock import patch

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource


@pytest.mark.asyncio
async def test_prepare_inbound_message_text_enriches_document_with_ingested_summary(tmp_path):
    from gateway.run import GatewayRunner

    doc = tmp_path / "brief.txt"
    doc.write_text("hello from the document")

    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(stt_enabled=True)
    runner.adapters = {}
    runner._model = "test-model"
    runner._base_url = ""
    runner._has_setup_skill = lambda: False

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm")
    event = MessageEvent(
        text="Please summarize this",
        message_type=MessageType.DOCUMENT,
        source=source,
        media_urls=[str(doc)],
        media_types=["text/plain"],
    )

    with patch(
        "tools.document_ingest.ingest_document",
        return_value={
            "success": True,
            "document_type": "text/plain",
            "summary": "Contains a short greeting.",
            "text_path": str(doc),
            "markdown_path": str(doc),
            "extracted_text": "hello from the document",
        },
    ):
        result = await runner._prepare_inbound_message_text(event=event, source=source, history=[])

    assert "Document summary: Contains a short greeting." in result
    assert "Extracted content:" in result
    assert "hello from the document" in result
    assert "Please summarize this" in result


@pytest.mark.asyncio
async def test_prepare_inbound_message_text_falls_back_when_document_ingest_fails(tmp_path):
    from gateway.run import GatewayRunner

    doc = tmp_path / "slides.pdf"
    doc.write_bytes(b"%PDF-1.4 fake")

    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(stt_enabled=True)
    runner.adapters = {}
    runner._model = "test-model"
    runner._base_url = ""
    runner._has_setup_skill = lambda: False

    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm")
    event = MessageEvent(
        text="",
        message_type=MessageType.DOCUMENT,
        source=source,
        media_urls=[str(doc)],
        media_types=["application/pdf"],
    )

    with patch(
        "tools.document_ingest.ingest_document",
        return_value={"success": False, "error": "converter unavailable"},
    ):
        result = await runner._prepare_inbound_message_text(event=event, source=source, history=[])

    assert "The user sent a document: 'slides.pdf'" in result
    assert "Ask the user what they'd like you to do with it." in result
