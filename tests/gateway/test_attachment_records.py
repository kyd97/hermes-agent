from gateway.platforms.base import AttachmentRecord, MessageEvent, MessageType, merge_pending_message_event


def test_message_event_backfills_attachments_from_legacy_media_lists():
    event = MessageEvent(
        text="",
        message_type=MessageType.DOCUMENT,
        media_urls=["/tmp/spec.pdf", "/tmp/photo.png"],
        media_types=["application/pdf", "image/png"],
    )

    assert [att.path for att in event.attachments] == ["/tmp/spec.pdf", "/tmp/photo.png"]
    assert [att.filename for att in event.attachments] == ["spec.pdf", "photo.png"]
    assert [att.media_type for att in event.attachments] == ["application/pdf", "image/png"]
    assert [att.kind for att in event.attachments] == ["document", "image"]


def test_message_event_backfills_legacy_media_lists_from_attachments():
    event = MessageEvent(
        text="",
        message_type=MessageType.PHOTO,
        attachments=[
            AttachmentRecord(
                path="/tmp/cached.jpg",
                filename="photo.jpg",
                media_type="image/jpeg",
                kind="image",
            )
        ],
    )

    assert event.media_urls == ["/tmp/cached.jpg"]
    assert event.media_types == ["image/jpeg"]


def test_message_event_prefers_structured_attachments_when_legacy_lists_are_partial():
    event = MessageEvent(
        text="",
        message_type=MessageType.DOCUMENT,
        media_urls=["/tmp/stale.bin"],
        media_types=[],
        attachments=[
            AttachmentRecord(
                path="/tmp/spec.pdf",
                filename="spec.pdf",
                media_type="application/pdf",
                kind="document",
            )
        ],
    )

    assert event.media_urls == ["/tmp/spec.pdf"]
    assert event.media_types == ["application/pdf"]


def test_merge_pending_message_event_merges_attachment_records_for_photo_bursts():
    pending = {}
    first = MessageEvent(
        text="first",
        message_type=MessageType.PHOTO,
        attachments=[
            AttachmentRecord(
                path="/tmp/a.jpg",
                filename="a.jpg",
                media_type="image/jpeg",
                kind="image",
            )
        ],
    )
    second = MessageEvent(
        text="second",
        message_type=MessageType.PHOTO,
        attachments=[
            AttachmentRecord(
                path="/tmp/b.jpg",
                filename="b.jpg",
                media_type="image/jpeg",
                kind="image",
            )
        ],
    )

    merge_pending_message_event(pending, "chat-1", first)
    merge_pending_message_event(pending, "chat-1", second)

    merged = pending["chat-1"]
    assert merged.media_urls == ["/tmp/a.jpg", "/tmp/b.jpg"]
    assert [att.filename for att in merged.attachments] == ["a.jpg", "b.jpg"]
    assert merged.text == "first\n\nsecond"
