"""Who is calling, and what they may do with a document.

Access levels, lowest to highest:
  viewer    -> read, see comments and history
  commenter -> + add comments, resolve their own
  editor    -> + edit, rename, restore versions, resolve any comment
  owner     -> + delete, manage sharing, delete any comment

Every route that works on an existing document calls get_access() first.
Users with no access get 404 (not 403), so document ids don't reveal what exists.
"""

import re
from typing import Optional

from fastapi import Header, HTTPException

from . import db

ROLE_RANK = {"viewer": 0, "commenter": 1, "editor": 2, "owner": 3}

# SQLite integers are 64-bit. Larger ids from the client would crash the query,
# so path/body ids are bounded to this.
MAX_ID = 2**63 - 1


def current_user(x_user_id: Optional[str] = Header(default=None)) -> dict:
    """Mocked auth: the client sends the selected seed user's id in X-User-Id."""
    if not x_user_id or not re.fullmatch(r"[0-9]{1,18}", x_user_id):
        raise HTTPException(401, "Missing or invalid X-User-Id header")
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (int(x_user_id),)).fetchone()
    if row is None:
        raise HTTPException(401, "Unknown user")
    return dict(row)


def get_access(conn, doc_id: int, user_id: int) -> tuple[dict, str]:
    """Return (document, role) or raise 404 if the user has no access."""
    doc = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc is None:
        raise HTTPException(404, "Document not found")
    if doc["owner_id"] == user_id:
        return dict(doc), "owner"
    share = conn.execute(
        "SELECT role FROM shares WHERE document_id = ? AND user_id = ?", (doc_id, user_id)
    ).fetchone()
    if share is None:
        raise HTTPException(404, "Document not found")
    return dict(doc), share["role"]


def require(role: str, minimum: str, message: str) -> None:
    if ROLE_RANK[role] < ROLE_RANK[minimum]:
        raise HTTPException(403, message)
