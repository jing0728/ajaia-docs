"""API tests for documents, sharing and import. Each test gets a fresh SQLite file
(see conftest.py), so they are independent.

Run from the backend folder:  python -m pytest
"""

import io
import zipfile

from conftest import ALICE, BOB, CAROL, create_doc

def test_requires_a_user(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/documents", headers={"X-User-Id": "999"}).status_code == 401


def test_create_rename_edit_and_reopen(client):
    doc = create_doc(client, ALICE, content="<p><strong>bold</strong> and <em>italic</em></p>")

    r = client.patch(
        f"/api/documents/{doc['id']}",
        json={"title": "Q4 Plan", "content": "<h1>Goals</h1><ul><li>ship</li></ul>", "base_version": doc["version"]},
        headers=ALICE,
    )
    assert r.status_code == 200
    assert r.json()["version"] == doc["version"] + 1

    reopened = client.get(f"/api/documents/{doc['id']}", headers=ALICE).json()
    assert reopened["title"] == "Q4 Plan"
    assert reopened["content"] == "<h1>Goals</h1><ul><li>ship</li></ul>"  # formatting survives


def test_sharing_controls_access(client):
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}"

    # Before sharing, Bob cannot see it at all (404, not 403, so ids don't leak).
    assert client.get(url, headers=BOB).status_code == 404

    # Bob cannot share Alice's document.
    assert client.post(f"{url}/shares", json={"email": "carol@ajaia.test"}, headers=BOB).status_code == 404

    # Alice shares with Bob as viewer: Bob can read, not edit, and sees it under "shared".
    r = client.post(f"{url}/shares", json={"email": "BOB@ajaia.test", "role": "viewer"}, headers=ALICE)
    assert r.status_code == 201
    assert client.get(url, headers=BOB).json()["role"] == "viewer"
    assert client.patch(url, json={"content": "<p>x</p>", "base_version": 1}, headers=BOB).status_code == 403
    lists = client.get("/api/documents", headers=BOB).json()
    assert [d["id"] for d in lists["shared"]] == [doc["id"]]
    assert lists["owned"] == []

    # Upgrade Bob to editor: now he can edit. Carol still has no access.
    r = client.post(f"{url}/shares", json={"email": "bob@ajaia.test", "role": "editor"}, headers=ALICE)
    assert r.status_code == 201
    assert client.patch(url, json={"content": "<p>x</p>", "base_version": 1}, headers=BOB).status_code == 200
    assert client.get(url, headers=CAROL).status_code == 404

    # Editors cannot delete or re-share; revoking access removes it again.
    assert client.delete(url, headers=BOB).status_code == 403
    assert client.post(f"{url}/shares", json={"email": "carol@ajaia.test"}, headers=BOB).status_code == 403
    assert client.delete(f"{url}/shares/2", headers=BOB).status_code == 403
    assert client.get("/api/documents", headers=ALICE).json()["owned"][0]["share_count"] == 1
    assert client.delete(f"{url}/shares/2", headers=ALICE).status_code == 204
    assert client.get(url, headers=BOB).status_code == 404


def test_stale_save_is_rejected(client):
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}"
    client.post(f"{url}/shares", json={"email": "bob@ajaia.test", "role": "editor"}, headers=ALICE)

    # Both opened version 1. Bob saves first; Alice's save based on version 1 must not overwrite it.
    assert client.patch(url, json={"content": "<p>bob</p>", "base_version": 1}, headers=BOB).status_code == 200
    assert client.patch(url, json={"content": "<p>alice</p>", "base_version": 1}, headers=ALICE).status_code == 409
    assert client.get(url, headers=ALICE).json()["content"] == "<p>bob</p>"


def test_title_only_rename_keeps_content(client):
    doc = create_doc(client, ALICE, content="<p>keep me</p>")
    r = client.patch(f"/api/documents/{doc['id']}", json={"title": "Renamed", "base_version": 1}, headers=ALICE)
    assert r.json()["title"] == "Renamed"
    assert r.json()["content"] == "<p>keep me</p>"


def test_html_is_sanitized(client):
    doc = create_doc(client, ALICE, content='<p onclick="x()">hi</p><script>alert(1)</script>')
    assert doc["content"] == "<p>hi</p>"
    doc = create_doc(client, ALICE, content='<p><a href="javascript:alert(1)">x</a></p>')
    assert "javascript" not in doc["content"]


def test_validation_errors(client):
    r = client.post("/api/documents", json={"title": "   "}, headers=ALICE)
    assert r.status_code == 422
    # Invisible characters don't count as a title; control characters are removed.
    assert client.post("/api/documents", json={"title": "​"}, headers=ALICE).status_code == 422
    assert create_doc(client, ALICE, title="a\x00b\nc")["title"] == "abc"
    # Ids beyond SQLite's 64-bit range are rejected cleanly instead of crashing (500).
    assert client.get(f"/api/documents/{2**70}", headers=ALICE).status_code == 422
    assert client.get("/api/documents", headers={"X-User-Id": "9" * 30}).status_code == 401
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}"
    assert client.patch(url, json={"content": "x", "base_version": 2**70}, headers=ALICE).status_code == 422
    assert client.patch(url, json={"content": "x", "base_version": "1"}, headers=ALICE).status_code == 422
    # A save with no fields is rejected, but only after the access check.
    assert client.patch(url, json={"base_version": 1}, headers=ALICE).status_code == 400
    assert client.patch(url, json={"base_version": 1}, headers=BOB).status_code == 404
    # A save whose values equal what's stored doesn't bump the version (no false conflicts)...
    same = client.patch(url, json={"title": doc["title"], "content": doc["content"], "base_version": 1}, headers=ALICE)
    assert same.status_code == 200 and same.json()["version"] == 1
    # ...but a stale one is still a conflict.
    client.patch(url, json={"content": "<p>new</p>", "base_version": 1}, headers=ALICE)
    assert client.patch(url, json={"title": doc["title"], "base_version": 1}, headers=ALICE).status_code == 409
    # The size limit applies after sanitizing: 250k "&" become 1.25M chars of "&amp;".
    r = client.patch(url, json={"content": "&" * 250_000, "base_version": 2}, headers=ALICE)
    assert r.status_code == 413
    doc = create_doc(client, ALICE)
    r = client.post(f"/api/documents/{doc['id']}/shares", json={"email": "nobody@x.com"}, headers=ALICE)
    assert r.status_code == 404


def upload(client, name, data, headers=ALICE):
    return client.post("/api/documents/import", files={"file": (name, io.BytesIO(data))}, headers=headers)


def test_import_markdown_becomes_formatted_document(client):
    r = upload(client, "meeting-notes.md", b"# Notes\n\n- **one**\n- two\n")
    assert r.status_code == 201
    doc = r.json()
    assert doc["title"] == "meeting-notes"
    assert "<h1>Notes</h1>" in doc["content"]
    assert "<strong>one</strong>" in doc["content"]


def test_import_text_escapes_html(client):
    r = upload(client, "a.txt", b"line <b>1</b>\n\nsecond para")
    assert r.json()["content"] == "<p>line &lt;b&gt;1&lt;/b&gt;</p><p>second para</p>"


def make_docx() -> bytes:
    """A minimal real .docx: a 'Heading 1' paragraph, a bold run, and a bulleted item."""
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/></Relationships>',
        # numId 1 -> a bullet list, so mammoth turns the paragraph into <ul><li>.
        "word/numbering.xml": f'<?xml version="1.0"?><w:numbering {w}>'
        '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>',
        "word/styles.xml": f'<?xml version="1.0"?><w:styles {w}><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style></w:styles>',
        "word/document.xml": f'<?xml version="1.0"?><w:document {w}><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Title</w:t></w:r></w:p>'
        '<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Bold</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>Item</w:t></w:r></w:p>'
        "</w:body></w:document>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, xml in files.items():
            z.writestr(name, xml)
    return buf.getvalue()


def test_import_docx_keeps_formatting(client):
    r = upload(client, "Report.docx", make_docx())
    assert r.status_code == 201, r.text
    html = r.json()["content"]
    assert "<h1>Title</h1>" in html
    assert "<strong>Bold</strong>" in html
    assert "<li>Item</li>" in html


def test_import_markdown_keeps_list_types_and_code(client):
    md = b"- one\n- two\n\n1. first\n2. second\n\n```\ncode block\n```\n"
    html = upload(client, "lists.md", md).json()["content"]
    assert "<ul>" in html and "<ol>" in html  # numbered list isn't merged into the bullets
    assert "<pre><code>code block" in html


def test_import_markdown_keeps_list_start_number(client):
    html = upload(client, "steps.md", b"3. First\n4. Second\n").json()["content"]
    assert '<ol start="3">' in html
    # Only a plain number is kept as a start value.
    doc = create_doc(client, ALICE, content='<ol start="x" onclick="y"><li>a</li></ol>')
    assert doc["content"] == "<ol><li>a</li></ol>"


def test_import_text_has_no_trailing_blank_line(client):
    assert upload(client, "a.txt", b"hello\n").json()["content"] == "<p>hello</p>"


def test_oversized_upload_rejected_before_parsing(client):
    # Declared Content-Length over the limit.
    assert upload(client, "huge.txt", b"a" * (3 * 1024 * 1024)).status_code == 413

    # Chunked upload with no Content-Length. Without the byte-counting middleware this
    # would be fully parsed and then rejected by content.py with 400; 413 proves the
    # middleware cut it off. (The test client buffers the body itself, so we can't
    # observe *when* the server stopped reading here; that was checked against a live
    # server with a streaming client.)
    def body():
        yield b'--b\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n\r\n'
        for _ in range(5):
            yield b"a" * (1024 * 1024)
        yield b"\r\n--b--\r\n"

    r = client.post(
        "/api/documents/import",
        content=body(),
        headers={**ALICE, "Content-Type": "multipart/form-data; boundary=b"},
    )
    assert r.status_code == 413


def test_docx_zip_bomb_rejected(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"<" + b"a" * (30 * 1024 * 1024))  # compresses to ~30 KB
    data = buf.getvalue()
    assert len(data) < 200_000
    r = upload(client, "bomb.docx", data)
    assert r.status_code == 400
    assert "too large" in r.json()["detail"]


def test_import_rejects_bad_files(client):
    assert upload(client, "photo.png", b"\x89PNG").status_code == 400
    assert upload(client, "empty.txt", b"").status_code == 400
    assert upload(client, "big.txt", b"a" * (2 * 1024 * 1024 + 1)).status_code == 400
    assert upload(client, "broken.docx", b"not a zip").status_code == 400
