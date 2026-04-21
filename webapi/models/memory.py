from webapi.models.common import WebAPIModel


class StructuredMemoryEntry(WebAPIModel):
    content: str
    memory_class: str


class MemoryPostRequest(WebAPIModel):
    target: str
    content: str
    memory_class: str | None = None


class MemoryPatchRequest(WebAPIModel):
    target: str
    old_text: str
    content: str
    memory_class: str | None = None


class MemoryDeleteRequest(WebAPIModel):
    target: str
    old_text: str


class MemoryMutationResponse(WebAPIModel):
    success: bool
    target: str
    entries: list[str]
    structured_entries: list[StructuredMemoryEntry]
    usage: str
    entry_count: int
    message: str | None = None


class MemoryTargetView(WebAPIModel):
    target: str
    entries: list[str]
    structured_entries: list[StructuredMemoryEntry]
    usage: str
    entry_count: int


class MemoryReadResponse(WebAPIModel):
    targets: list[MemoryTargetView]
