"""SQLite storage: schema, seed data, and a connection helper.

We use the standard-library sqlite3 module directly instead of an ORM.
The schema is a handful of small tables, so plain SQL is easier to read and review.
"""

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS documents (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL DEFAULT '',   -- sanitized HTML produced by the editor
    owner_id   INTEGER NOT NULL REFERENCES users(id),
    version    INTEGER NOT NULL DEFAULT 1, -- bumped on every save, used to detect conflicts
    updated_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Access levels, lowest to highest: viewer < commenter < editor (< owner, implied by owner_id).
CREATE TABLE IF NOT EXISTS shares (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    role        TEXT NOT NULL CHECK (role IN ('viewer', 'commenter', 'editor')),
    PRIMARY KEY (document_id, user_id)
);

-- Version history. Autosave runs every few seconds, so instead of one row per save we keep
-- one row per "editing burst": a save by the same person within a minute of their last
-- snapshot updates that snapshot instead of adding a new one.
CREATE TABLE IF NOT EXISTS document_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    saved_by    INTEGER NOT NULL REFERENCES users(id),
    note        TEXT,                  -- e.g. "Created", "Imported from notes.md", "Restored"
    created_at  REAL NOT NULL          -- unix seconds
);

CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    body        TEXT NOT NULL,
    quote       TEXT,                  -- text that was selected when commenting, if any
    resolved    INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

-- Who has a document open right now (heartbeat every few seconds).
CREATE TABLE IF NOT EXISTS presence (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    last_seen   REAL NOT NULL,
    PRIMARY KEY (document_id, user_id)
);
"""

# Mocked accounts. There is no password login: the frontend picks one of these
# users and sends its id in the X-User-Id header.
SEED_USERS = [
    (1, "Alice Chen", "alice@ajaia.test"),
    (2, "Bob Martinez", "bob@ajaia.test"),
    (3, "Carol Singh", "carol@ajaia.test"),
]

WELCOME_DOC = """<h1>Welcome to Ajaia Docs</h1>
<p>This document is owned by <strong>Alice</strong>, shared with <strong>Bob</strong> as an editor and with <strong>Carol</strong> as a commenter.</p>
<h2>Try it</h2>
<ol>
<li><p>Format text with the toolbar: <strong>bold</strong>, <em>italic</em>, <u>underline</u>, headings, lists.</p></li>
<li><p>Switch user (top right) to Bob and open this from <em>Shared with me</em>. Open it as Alice in a second tab to see who else is here.</p></li>
<li><p>Select some text and add a comment, or open <em>History</em> to restore an older version.</p></li>
<li><p>Import a .txt, .md or .docx file from the sidebar, or export this one as PDF or Markdown.</p></li>
</ol>"""


def seed_demo_documents(conn) -> None:
    """Give reviewers something to look at on a fresh database."""
    if conn.execute("SELECT 1 FROM documents LIMIT 1").fetchone():
        return
    cur = conn.execute(
        "INSERT INTO documents (title, content, owner_id, updated_by) VALUES (?, ?, 1, 1)",
        ("Welcome to Ajaia Docs", WELCOME_DOC),
    )
    doc_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO shares (document_id, user_id, role) VALUES (?, ?, ?)",
        [(doc_id, 2, "editor"), (doc_id, 3, "commenter")],
    )
    conn.execute(
        """INSERT INTO document_versions (document_id, version, title, content, saved_by, note, created_at)
           VALUES (?, 1, ?, ?, 1, 'Created', ?)""",
        (doc_id, "Welcome to Ajaia Docs", WELCOME_DOC, time.time()),
    )
    conn.execute(
        "INSERT INTO comments (document_id, user_id, body, quote, created_at) VALUES (?, 3, ?, ?, ?)",
        (doc_id, "Should we add a section on keyboard shortcuts?", "Format text with the toolbar", time.time()),
    )


def db_path() -> str:
    return os.environ.get("DB_PATH", str(DEFAULT_DB_PATH))


def init_db() -> None:
    path = db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT OR IGNORE INTO users (id, name, email) VALUES (?, ?, ?)", SEED_USERS
        )
        if os.environ.get("SEED_DEMO_DOCS", "1") == "1":
            seed_demo_documents(conn)


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
