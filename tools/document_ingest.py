"""Lightweight document ingest helpers for gateway/document workflows.

Initial scope:
- text-like files: return decoded content directly
- JSON / CSV / XML / YAML / TOML / INI: treat as text when decodable
- PDF / DOCX / PPTX / XLSX: best-effort extraction with optional deps or zip/XML fallback

This module is intentionally registry-free so gateway code can import it without
pulling in the full tool system.
"""

from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import re
import zipfile
from configparser import ConfigParser
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".log", ".json", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg"
}


def _guess_document_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def _safe_read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except Exception:
            continue
    return data.decode("utf-8", errors="replace")


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _summarize_text(text: str, *, max_chars: int = 280) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return "No extractable text found."
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages[:20]:
            pages.append(page.extract_text() or "")
        return _clean_text("\n\n".join(pages))
    except Exception:
        return ""


def _extract_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        text_nodes = [node.text for node in root.iter() if node.text]
        return _clean_text(" ".join(text_nodes))
    except Exception:
        return ""


def _extract_pptx(path: Path) -> str:
    try:
        slide_text = []
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(name for name in zf.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            for name in slide_names[:20]:
                root = ET.fromstring(zf.read(name))
                bits = [node.text for node in root.iter() if node.text]
                if bits:
                    slide_text.append(" ".join(bits))
        return _clean_text("\n\n".join(slide_text))
    except Exception:
        return ""


def _extract_xlsx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            shared_strings = []
            if "xl/sharedStrings.xml" in zf.namelist():
                root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
                shared_strings = [node.text or "" for node in root.iter() if node.tag.endswith("}t") or node.tag == "t"]

            sheets = []
            sheet_names = sorted(name for name in zf.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
            for name in sheet_names[:10]:
                root = ET.fromstring(zf.read(name))
                values = []
                for cell in root.iter():
                    if not cell.tag.endswith("}c") and cell.tag != "c":
                        continue
                    cell_type = cell.attrib.get("t")
                    value_node = next((child for child in cell if child.tag.endswith("}v") or child.tag == "v"), None)
                    if value_node is None or value_node.text is None:
                        continue
                    value = value_node.text
                    if cell_type == "s":
                        try:
                            idx = int(value)
                            value = shared_strings[idx]
                        except Exception:
                            pass
                    values.append(value)
                if values:
                    sheets.append(", ".join(values))
        return _clean_text("\n\n".join(sheets))
    except Exception:
        return ""


def ingest_document(path: str, *, max_chars: int = 4000) -> dict[str, Any]:
    doc_path = Path(path)
    if not doc_path.exists():
        return {"success": False, "error": f"File not found: {path}"}

    ext = doc_path.suffix.lower()
    document_type = _guess_document_type(doc_path)
    extracted = ""

    try:
        if ext in _TEXT_EXTENSIONS or document_type.startswith("text/"):
            extracted = _safe_read_text(doc_path)
        elif ext == ".pdf":
            extracted = _extract_pdf(doc_path)
        elif ext == ".docx":
            extracted = _extract_docx(doc_path)
        elif ext == ".pptx":
            extracted = _extract_pptx(doc_path)
        elif ext == ".xlsx":
            extracted = _extract_xlsx(doc_path)
    except Exception as exc:
        return {"success": False, "error": str(exc), "document_type": document_type}

    extracted = _clean_text(extracted)
    summary = _summarize_text(extracted)
    extracted_snippet = extracted[:max_chars]

    if not extracted_snippet and summary == "No extractable text found.":
        return {
            "success": False,
            "error": "No extractable text found.",
            "path": str(doc_path),
            "document_type": document_type,
        }

    return {
        "success": True,
        "path": str(doc_path),
        "document_type": document_type,
        "summary": summary,
        "extracted_text": extracted_snippet,
        "text_path": str(doc_path) if extracted_snippet else "",
        "markdown_path": str(doc_path) if ext in {'.md', '.txt'} else "",
        "truncated": len(extracted) > max_chars,
    }
