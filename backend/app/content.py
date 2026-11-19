"""Turning user input into safe HTML.

Everything that ends up in documents.content goes through sanitize_html(), whether it
came from the editor or from an uploaded file. A shared document is rendered in
another user's browser, so we never store raw HTML from the client.
"""

import html
import io
import unicodedata
import zipfile
from pathlib import Path

import mammoth
import markdown
import nh3

# Tags the editor can produce. Anything else is stripped (its text is kept).
ALLOWED_TAGS = {
    "p", "br", "h1", "h2", "h3", "strong", "b", "em", "i", "u", "s",
    "ul", "ol", "li", "blockquote", "code", "pre", "hr", "a",
}
ALLOWED_ATTRIBUTES = {"a": {"href"}, "ol": {"start"}}  # start: a list that begins at 3, etc.


def _filter_attribute(tag: str, attr: str, value: str):
    """Extra check on allowed attributes: a list's start number must be a small integer."""
    if tag == "ol" and attr == "start":
        return value if value.isdigit() and len(value) <= 6 else None
    return value

SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024  # 2 MB is plenty for text documents
# A .docx is a zip. Its compressed size can be tiny while it expands to gigabytes
# (a "zip bomb"), so we also cap the uncompressed size before converting it.
MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
MAX_CONTENT_CHARS = 1_000_000
MAX_TITLE_CHARS = 200


class FileImportError(ValueError):
    """Raised when an uploaded file cannot be turned into a document."""


def sanitize_html(raw: str) -> str:
    return nh3.clean(raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, attribute_filter=_filter_attribute)


def clean_title(raw: str) -> str:
    """Remove control and invisible formatting characters (e.g. NUL, zero-width space)
    so a title can't look blank or break the UI, then trim whitespace."""
    visible = "".join(ch for ch in raw if unicodedata.category(ch) not in ("Cc", "Cf"))
    return visible.strip()[:MAX_TITLE_CHARS]


def text_to_html(text: str) -> str:
    # Blank lines separate paragraphs; single newlines become <br>.
    paragraphs = [p.strip("\n") for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return "".join(
        "<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in paragraphs
    )


def _check_docx_size(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            total = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile as exc:
        raise FileImportError("Could not read this .docx file.") from exc
    if total > MAX_DOCX_UNCOMPRESSED_BYTES:
        raise FileImportError("This .docx file is too large once unpacked.")


def file_to_html(filename: str, data: bytes) -> str:
    """Convert an uploaded .txt / .md / .docx file into sanitized HTML."""
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise FileImportError(
            f"Unsupported file type '{ext or 'none'}'. Supported: .txt, .md, .docx"
        )
    if len(data) == 0:
        raise FileImportError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileImportError("File is larger than 2 MB.")

    if ext == ".docx":
        _check_docx_size(data)
        try:
            result = mammoth.convert_to_html(io.BytesIO(data))
        except Exception as exc:  # mammoth raises a variety of zip/xml errors
            raise FileImportError("Could not read this .docx file.") from exc
        converted = result.value
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise FileImportError("Text files must be UTF-8 encoded.") from exc
        if ext == ".md":
            # "extra" adds fenced code blocks and tables; "sane_lists" keeps a numbered
            # list that follows a bulleted one from being merged into it.
            converted = markdown.markdown(text, extensions=["extra", "sane_lists"])
        else:
            converted = text_to_html(text)

    result_html = sanitize_html(converted)
    if len(result_html) > MAX_CONTENT_CHARS:
        raise FileImportError("This file has too much content to import.")
    return result_html


def title_from_filename(filename: str) -> str:
    return clean_title(Path(filename).stem) or "Imported document"
