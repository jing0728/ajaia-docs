"""FastAPI app: documents, file import, sharing, and serving the frontend.

Access rules live in access.py; version history, comments and presence in collab.py.
"""

from contextlib import asynccontextmanager
from pathlib import Path as FsPath
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Path, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt

from . import db
from .access import MAX_ID, current_user, get_access, require
from .collab import record_version, router as collab_router
from .content import (
    MAX_CONTENT_CHARS,
    MAX_UPLOAD_BYTES,
    FileImportError,
    clean_title,
    file_to_html,
    sanitize_html,
    title_from_filename,
)

IMPORT_PATH = "/api/documents/import"
# Multipart wraps the file in a few hundred bytes of headers; allow some slack.
MAX_IMPORT_BODY_BYTES = MAX_UPLOAD_BYTES + 64 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Ajaia Docs", lifespan=lifespan)
app.include_router(collab_router)


# ---------- middleware ----------

class LimitImportBody:
    """Stop reading an upload as soon as it passes the size limit.

    FastAPI reads the whole multipart body before the endpoint runs, so checking the file
    size inside the endpoint is too late: a huge (or chunked, length-less) upload would be
    fully received first. This wraps the raw ASGI receive channel and counts bytes.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != IMPORT_PATH:
            return await self.app(scope, receive, send)

        headers = dict(scope["headers"])
        declared = headers.get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_IMPORT_BODY_BYTES):
            return await JSONResponse({"detail": "File is larger than 2 MB."}, 413)(scope, receive, send)

        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_IMPORT_BODY_BYTES:
                    # FastAPI turns this into a normal 413 JSON response.
                    raise HTTPException(413, "File is larger than 2 MB.")
            return message

        await self.app(scope, limited_receive, send)


app.add_middleware(LimitImportBody)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    # Defence in depth in case sanitizing ever misses something: no inline or third-party
    # scripts, and the app can't be embedded in another site's frame.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# ---------- request bodies ----------



class CreateDoc(BaseModel):
    title: str = Field(default="Untitled document", max_length=1000)
    content: str = Field(default="", max_length=MAX_CONTENT_CHARS)


class UpdateDoc(BaseModel):
    title: Optional[str] = Field(default=None, max_length=1000)
    content: Optional[str] = Field(default=None, max_length=MAX_CONTENT_CHARS)
    # The version the client last saw. If someone else saved since, we reject
    # with 409 instead of silently overwriting their work.
    base_version: StrictInt = Field(ge=0, le=MAX_ID)


class ShareRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: Literal["viewer", "commenter", "editor"] = "viewer"


def valid_title(raw: str) -> str:
    title = clean_title(raw)
    if not title:
        raise HTTPException(422, "Title cannot be blank")
    return title


def doc_out(conn, doc: dict, role: str) -> dict:
    owner = conn.execute("SELECT name, email FROM users WHERE id = ?", (doc["owner_id"],)).fetchone()
    return {
        "id": doc["id"],
        "title": doc["title"],
        "content": doc["content"],
        "version": doc["version"],
        "updated_at": doc["updated_at"],
        "owner": {"id": doc["owner_id"], "name": owner["name"], "email": owner["email"]},
        "role": role,
    }


# ---------- users ----------

@app.get("/api/users")
def list_users():
    with db.connect() as conn:
        rows = conn.execute("SELECT id, name, email FROM users ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ---------- documents ----------

@app.get("/api/documents")
def list_documents(user: dict = Depends(current_user)):
    """Documents split into the two groups the sidebar shows."""
    with db.connect() as conn:
        owned = conn.execute(
            """SELECT d.id, d.title, d.updated_at,
                      (SELECT COUNT(*) FROM shares s WHERE s.document_id = d.id) AS share_count
               FROM documents d WHERE d.owner_id = ? ORDER BY d.updated_at DESC, d.id DESC""",
            (user["id"],),
        ).fetchall()
        shared = conn.execute(
            """SELECT d.id, d.title, d.updated_at, s.role, u.name AS owner_name
               FROM shares s
               JOIN documents d ON d.id = s.document_id
               JOIN users u ON u.id = d.owner_id
               WHERE s.user_id = ?
               ORDER BY d.updated_at DESC, d.id DESC""",
            (user["id"],),
        ).fetchall()
    return {"owned": [dict(r) for r in owned], "shared": [dict(r) for r in shared]}


def insert_document(conn, owner_id: int, title: str, content: str, note: str) -> dict:
    content = sanitize_html(content)
    if len(content) > MAX_CONTENT_CHARS:
        raise HTTPException(413, "Document is too large")
    cur = conn.execute(
        "INSERT INTO documents (title, content, owner_id, updated_by) VALUES (?, ?, ?, ?)",
        (title, content, owner_id, owner_id),
    )
    doc = dict(conn.execute("SELECT * FROM documents WHERE id = ?", (cur.lastrowid,)).fetchone())
    record_version(conn, doc, owner_id, note=note)
    return doc_out(conn, doc, "owner")


@app.post("/api/documents", status_code=201)
def create_document(body: CreateDoc, user: dict = Depends(current_user)):
    title = valid_title(body.title)
    with db.connect() as conn:
        return insert_document(conn, user["id"], title, body.content, note="Created")


@app.post(IMPORT_PATH, status_code=201)
def import_document(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """Upload a .txt, .md or .docx file and turn it into a new editable document.

    A plain (sync) def on purpose: .docx conversion is CPU work, and FastAPI runs sync
    endpoints in a thread pool so one big import can't freeze every other request.
    """
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    filename = file.filename or ""
    try:
        html = file_to_html(filename, data)
    except FileImportError as exc:
        raise HTTPException(400, str(exc))
    with db.connect() as conn:
        return insert_document(
            conn, user["id"], title_from_filename(filename), html,
            note=f"Imported from {FsPath(filename).name[:100]}",
        )


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        doc, role = get_access(conn, doc_id, user["id"])
        return doc_out(conn, doc, role)


@app.patch("/api/documents/{doc_id}")
def update_document(body: UpdateDoc, doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        # Access first, so the response never reveals anything about a document you can't see.
        doc, role = get_access(conn, doc_id, user["id"])
        require(role, "editor", "You don't have edit access to this document")
        if body.title is None and body.content is None:
            raise HTTPException(400, "Nothing to update")

        title = valid_title(body.title) if body.title is not None else doc["title"]
        content = sanitize_html(body.content) if body.content is not None else doc["content"]
        # Checked after sanitizing: escaping can make the stored HTML longer than the input
        # (e.g. every "&" becomes "&amp;").
        if len(content) > MAX_CONTENT_CHARS:
            raise HTTPException(413, "Document is too large")

        if title == doc["title"] and content == doc["content"]:
            # Nothing actually changed: don't bump the version (that would give other
            # editors a false conflict). A stale base_version is still a conflict.
            if body.base_version != doc["version"]:
                raise HTTPException(409, "This document was changed by someone else. Reload to see the latest version.")
            return doc_out(conn, doc, role)

        # Compare-and-swap on version: only succeeds if nobody saved in between.
        cur = conn.execute(
            """UPDATE documents
               SET title = ?, content = ?, version = version + 1, updated_by = ?, updated_at = datetime('now')
               WHERE id = ? AND version = ?""",
            (title, content, user["id"], doc_id, body.base_version),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "This document was changed by someone else. Reload to see the latest version.")
        doc, role = get_access(conn, doc_id, user["id"])
        record_version(conn, doc, user["id"])
        return doc_out(conn, doc, role)


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        _, role = get_access(conn, doc_id, user["id"])
        require(role, "owner", "Only the owner can delete this document")
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))


# ---------- sharing ----------

@app.get("/api/documents/{doc_id}/shares")
def list_shares(doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        get_access(conn, doc_id, user["id"])  # any collaborator can see who has access
        rows = conn.execute(
            """SELECT u.id, u.name, u.email, s.role FROM shares s
               JOIN users u ON u.id = s.user_id WHERE s.document_id = ? ORDER BY u.name""",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/documents/{doc_id}/shares", status_code=201)
def share_document(body: ShareRequest, doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        _, role = get_access(conn, doc_id, user["id"])
        require(role, "owner", "Only the owner can share this document")
        target = conn.execute(
            "SELECT id, name, email FROM users WHERE lower(email) = lower(?)", (body.email.strip(),)
        ).fetchone()
        if target is None:
            raise HTTPException(404, f"No user with email {body.email.strip()}")
        if target["id"] == user["id"]:
            raise HTTPException(400, "You already own this document")
        # Sharing again with the same person just updates their role.
        conn.execute(
            """INSERT INTO shares (document_id, user_id, role) VALUES (?, ?, ?)
               ON CONFLICT (document_id, user_id) DO UPDATE SET role = excluded.role""",
            (doc_id, target["id"], body.role),
        )
    return {**dict(target), "role": body.role}


@app.delete("/api/documents/{doc_id}/shares/{target_user_id}", status_code=204)
def unshare_document(doc_id: int = Path(ge=1, le=MAX_ID), target_user_id: int = Path(ge=1, le=MAX_ID),
                     user: dict = Depends(current_user)):
    with db.connect() as conn:
        _, role = get_access(conn, doc_id, user["id"])
        require(role, "owner", "Only the owner can change sharing")
        conn.execute(
            "DELETE FROM shares WHERE document_id = ? AND user_id = ?", (doc_id, target_user_id)
        )


# ---------- frontend ----------
# In production the built React app (frontend/dist) is served by this same process,
# so the whole product deploys as one service.

FRONTEND_DIST = FsPath(__file__).resolve().parents[2] / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.split("/")[0].lower() == "api":
            raise HTTPException(404, "Not found")
        return FileResponse(FRONTEND_DIST / "index.html")
