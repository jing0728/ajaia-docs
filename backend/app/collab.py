"""Collaboration features around a document: version history, comments, presence."""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field, StrictBool, StrictInt

from . import db
from .access import MAX_ID, current_user, get_access, require

router = APIRouter(prefix="/api/documents/{doc_id}")


SNAPSHOT_WINDOW_SECONDS = 60  # saves by the same person within this window share one snapshot
PRESENCE_TIMEOUT_SECONDS = 30  # someone counts as "here" if seen this recently


# ---------- version history ----------

def record_version(conn, doc: dict, user_id: int, note: Optional[str] = None) -> None:
    """Snapshot the document's current state into document_versions.

    Called after every successful save. Autosave runs every second or so while typing,
    so consecutive saves by the same person are folded into their latest snapshot.
    A note (create / import / restore) always starts a new snapshot.
    """
    now = time.time()
    latest = conn.execute(
        "SELECT id, saved_by, created_at, note FROM document_versions WHERE document_id = ? ORDER BY id DESC LIMIT 1",
        (doc["id"],),
    ).fetchone()
    same_burst = (
        latest is not None
        and note is None
        and latest["note"] is None
        and latest["saved_by"] == user_id
        and now - latest["created_at"] < SNAPSHOT_WINDOW_SECONDS
    )
    if same_burst:
        conn.execute(
            "UPDATE document_versions SET version = ?, title = ?, content = ? WHERE id = ?",
            (doc["version"], doc["title"], doc["content"], latest["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO document_versions (document_id, version, title, content, saved_by, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (doc["id"], doc["version"], doc["title"], doc["content"], user_id, note, now),
        )


@router.get("/versions")
def list_versions(doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        get_access(conn, doc_id, user["id"])
        rows = conn.execute(
            """SELECT v.id, v.version, v.title, v.note, v.created_at, u.name AS saved_by_name
               FROM document_versions v JOIN users u ON u.id = v.saved_by
               WHERE v.document_id = ? ORDER BY v.id DESC LIMIT 100""",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/versions/{version_id}")
def get_version(doc_id: int = Path(ge=1, le=MAX_ID), version_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        get_access(conn, doc_id, user["id"])
        row = conn.execute(
            "SELECT id, version, title, content, created_at FROM document_versions WHERE id = ? AND document_id = ?",
            (version_id, doc_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Version not found")
    return dict(row)


class RestoreRequest(BaseModel):
    base_version: StrictInt = Field(ge=0, le=MAX_ID)
    # The snapshot's version as the user previewed it. The newest snapshot is updated in
    # place while its author keeps typing, so without this check you could restore
    # different content from what you looked at and confirmed.
    snapshot_version: StrictInt = Field(ge=0, le=MAX_ID)


@router.post("/versions/{version_id}/restore")
def restore_version(body: RestoreRequest, doc_id: int = Path(ge=1, le=MAX_ID), version_id: int = Path(ge=1, le=MAX_ID),
                    user: dict = Depends(current_user)):
    """Restoring is just another save: it creates a new version, so it can be undone."""
    from .main import doc_out  # local import: main imports this module

    with db.connect() as conn:
        _, role = get_access(conn, doc_id, user["id"])
        require(role, "editor", "Only editors can restore versions")
        old = conn.execute(
            "SELECT title, content, version, created_at FROM document_versions WHERE id = ? AND document_id = ?",
            (version_id, doc_id),
        ).fetchone()
        if old is None:
            raise HTTPException(404, "Version not found")
        if old["version"] != body.snapshot_version:
            raise HTTPException(409, "This version has changed since you previewed it. Preview it again before restoring.")
        cur = conn.execute(
            """UPDATE documents SET title = ?, content = ?, version = version + 1, updated_by = ?,
                      updated_at = datetime('now')
               WHERE id = ? AND version = ?""",
            (old["title"], old["content"], user["id"], doc_id, body.base_version),
        )
        if cur.rowcount == 0:
            raise HTTPException(409, "This document was changed by someone else. Reload to see the latest version.")
        doc, role = get_access(conn, doc_id, user["id"])
        when = time.strftime("%b %d, %H:%M", time.gmtime(old["created_at"]))
        record_version(conn, doc, user["id"], note=f"Restored version from {when} UTC")
        return doc_out(conn, doc, role)


# ---------- comments ----------

class NewComment(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    quote: Optional[str] = Field(default=None, max_length=500)


class UpdateComment(BaseModel):
    resolved: StrictBool


def comment_out(row) -> dict:
    return {k: row[k] for k in row.keys()} | {"resolved": bool(row["resolved"])}


COMMENT_SELECT = """SELECT c.id, c.body, c.quote, c.resolved, c.created_at, c.user_id, u.name AS author
                    FROM comments c JOIN users u ON u.id = c.user_id"""


@router.get("/comments")
def list_comments(doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    with db.connect() as conn:
        get_access(conn, doc_id, user["id"])
        rows = conn.execute(f"{COMMENT_SELECT} WHERE c.document_id = ? ORDER BY c.id", (doc_id,)).fetchall()
    return [comment_out(r) for r in rows]


@router.post("/comments", status_code=201)
def add_comment(body: NewComment, doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    text = body.body.strip()
    if not text:
        raise HTTPException(422, "Comment cannot be blank")
    quote = (body.quote or "").strip() or None
    with db.connect() as conn:
        _, role = get_access(conn, doc_id, user["id"])
        require(role, "commenter", "You have view-only access to this document")
        cur = conn.execute(
            "INSERT INTO comments (document_id, user_id, body, quote, created_at) VALUES (?, ?, ?, ?, ?)",
            (doc_id, user["id"], text, quote, time.time()),
        )
        row = conn.execute(f"{COMMENT_SELECT} WHERE c.id = ?", (cur.lastrowid,)).fetchone()
    return comment_out(row)


def _load_comment(conn, doc_id: int, comment_id: int):
    row = conn.execute(
        "SELECT * FROM comments WHERE id = ? AND document_id = ?", (comment_id, doc_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Comment not found")
    return row


@router.patch("/comments/{comment_id}")
def update_comment(body: UpdateComment, doc_id: int = Path(ge=1, le=MAX_ID), comment_id: int = Path(ge=1, le=MAX_ID),
                   user: dict = Depends(current_user)):
    """Resolve or reopen. Editors and the owner can resolve any comment; commenters their own.

    Authors still need at least commenter access: someone downgraded to viewer can no longer
    change comments, including ones they wrote earlier.
    """
    with db.connect() as conn:
        _, role = get_access(conn, doc_id, user["id"])
        require(role, "commenter", "You have view-only access to this document")
        comment = _load_comment(conn, doc_id, comment_id)
        if comment["user_id"] != user["id"]:
            require(role, "editor", "Only editors can resolve other people's comments")
        conn.execute("UPDATE comments SET resolved = ? WHERE id = ?", (int(body.resolved), comment_id))
        row = conn.execute(f"{COMMENT_SELECT} WHERE c.id = ?", (comment_id,)).fetchone()
    return comment_out(row)


@router.delete("/comments/{comment_id}", status_code=204)
def delete_comment(doc_id: int = Path(ge=1, le=MAX_ID), comment_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    """Authors (with at least commenter access) can delete their own comments; the owner can delete any."""
    with db.connect() as conn:
        _, role = get_access(conn, doc_id, user["id"])
        require(role, "commenter", "You have view-only access to this document")
        comment = _load_comment(conn, doc_id, comment_id)
        if comment["user_id"] != user["id"]:
            require(role, "owner", "Only the owner can delete other people's comments")
        conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))


# ---------- presence ----------

@router.post("/presence")
def heartbeat(doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    """Called every few seconds by an open editor.

    Records that this user is here and returns who else is, the document's current version
    (so the client can tell when someone else has saved) and the caller's current role (so
    an open editor locks right away if the owner downgrades or removes them; a removed
    user gets 404 here).
    """
    now = time.time()
    with db.connect() as conn:
        doc, role = get_access(conn, doc_id, user["id"])
        conn.execute(
            """INSERT INTO presence (document_id, user_id, last_seen) VALUES (?, ?, ?)
               ON CONFLICT (document_id, user_id) DO UPDATE SET last_seen = excluded.last_seen""",
            (doc_id, user["id"], now),
        )
        others = conn.execute(
            """SELECT u.id, u.name FROM presence p JOIN users u ON u.id = p.user_id
               WHERE p.document_id = ? AND p.user_id != ? AND p.last_seen > ? ORDER BY u.name""",
            (doc_id, user["id"], now - PRESENCE_TIMEOUT_SECONDS),
        ).fetchall()
        editor = conn.execute("SELECT name FROM users WHERE id = ?", (doc["updated_by"],)).fetchone()
    return {
        "others": [dict(r) for r in others],
        "version": doc["version"],
        "role": role,
        "updated_by": {"id": doc["updated_by"], "name": editor["name"]} if editor else None,
    }


@router.delete("/presence", status_code=204)
def leave(doc_id: int = Path(ge=1, le=MAX_ID), user: dict = Depends(current_user)):
    """Remove the caller's own presence row. Deliberately no get_access(): it can only
    delete your own row, and must still work right after your access was revoked.
    Idempotent: returns 204 even if there was nothing to delete."""
    with db.connect() as conn:
        conn.execute("DELETE FROM presence WHERE document_id = ? AND user_id = ?", (doc_id, user["id"]))
