# Ajaia Docs

A lightweight collaborative document editor. You can create and format documents in the browser, import files, share them as editor, commenter or viewer, comment on them, see who else has a document open, browse and restore past versions, and export to PDF or Markdown.

**Live app:** `TODO: paste Render URL here`

> **Note on the hosted demo:** it runs on Render's free tier, which has no persistent disk. The service sleeps after ~15 minutes idle; the first visit after that takes 30-60 s to wake, and **documents created earlier are reset** (the seeded welcome document comes back). Within a session, everything persists across refreshes. Running locally keeps all data. See [Deployment](#deployment).

## Demo accounts

There is no password login. Pick a user from the **Signed in as** menu at the top right.

| User | Email | On the seeded *Welcome* document |
|---|---|---|
| Alice Chen | alice@ajaia.test | Owner |
| Bob Martinez | bob@ajaia.test | Can edit |
| Carol Singh | carol@ajaia.test | Can comment |

**Try the sharing flow:** as Alice, create a document → **Share** → enter `bob@ajaia.test`, pick *View only* → switch to Bob → the document appears under **Shared with me**, read-only, with no toolbar.

**Try collaboration:** open *Welcome* as Alice in one tab and as Bob in another (switch the user in the second tab, then reload). Each tab shows the other person's avatar. Type in Bob's tab, and within ~5 s Alice's tab updates with his changes.

## Features

- **Documents:** create, rename (click the title), edit, delete (owner only). Autosaves 0.8 s after you stop typing, with a visible save status. Failed saves retry automatically, and you're told if changes couldn't be saved.
- **Formatting:** bold, italic, underline, strikethrough, headings H1–H3, bulleted and numbered lists, quotes, links, undo/redo. Keyboard shortcuts work (Ctrl+B / I / U / Z).
- **File import:** `.txt`, `.md` and `.docx`, up to 2 MB. Each file becomes a new editable document. Headings, bold, italic, lists (including a numbered list's start number), code blocks and links are kept. Not supported: images and tables (table text is kept, layout is not), H4–H6 become plain paragraphs, and Word underline is not carried over. Other file types are rejected with a clear message.
- **Sharing with roles:** the owner shares by email as **Can edit**, **Can comment** or **View only**, and can change the role or remove access. The sidebar separates **My documents** (with a "Shared with N" badge) from **Shared with me** (with the owner and your access level).

  | | View only | Can comment | Can edit | Owner |
  |---|---|---|---|---|
  | Read, see comments and history | ✓ | ✓ | ✓ | ✓ |
  | Add comments, resolve own | | ✓ | ✓ | ✓ |
  | Edit, rename, restore versions, resolve any comment | | | ✓ | ✓ |
  | Share, delete document, delete any comment | | | | ✓ |

- **Comments:** comment on the whole document, optionally quoting the selected text (click the quote to jump to it). Resolve/reopen, delete.
- **Version history:** one snapshot per editing session (saves by the same person within a minute are grouped). Preview any version and restore it. Restoring creates a new version, so it can be undone.
- **Presence and live updates:** avatars show who else has the document open. When someone else saves and you have no unsaved changes, your view updates in place. If the owner changes or removes your access, your open editor locks within ~5 s.
- **Conflict protection:** if two people edit at the same time, the second save is rejected instead of silently overwriting. Your unsaved text stays on screen with a **Copy my text** button, and the browser warns before you close the tab.
- **Export:** PDF (the browser's print dialog, using a clean document-only print layout) and Markdown (`.md` download).

## Run locally

Requires Python 3.11+ and Node 18+.

**1. Backend.** Windows (PowerShell):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

macOS / Linux:

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

**2. Frontend** (second terminal):

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Vite forwards `/api` calls to the backend on port 8000. If your backend runs on a different port, set `API_URL` (e.g. `API_URL=http://localhost:8010`) before `npm run dev`.

**Single-process mode (same as production):** in `frontend/` run `npm install` (if you haven't) and `npm run build`, then start only the backend (the `--reload` flag is optional) and open http://localhost:8000. FastAPI serves the built UI.

The SQLite database is created at `backend/data/app.db`. Delete that file to reset to the seed data.

## Tests

Windows (PowerShell):

```powershell
cd backend
.venv\Scripts\python -m pytest
```

macOS / Linux:

```bash
cd backend
.venv/bin/python -m pytest
```

23 API tests, each on a fresh database:

- **Documents and sharing** (`tests/test_api.py`):
  - Create, rename, edit and reopen with formatting preserved.
  - The permission matrix across roles.
  - Stale-save conflict detection.
  - Sanitization of scripts, event handlers and `javascript:` links.
  - Input validation: blank or invisible titles, oversized ids, saves that change nothing.
  - File import: Markdown lists and code, plain text, a real .docx, rejected types, size limits including chunked uploads, a .docx zip bomb.
- **Collaboration** (`tests/test_collab.py`):
  - Version grouping, restore, and stale restore.
  - History permissions.
  - The commenter role.
  - Comment resolve and delete rules.
  - Presence, including expiry.

There are no automated frontend tests; the UI flows were checked in a browser (see [AI_WORKFLOW.md](AI_WORKFLOW.md)).

## Deployment

Runs on Render's free tier as one Docker service (see `Dockerfile` and `render.yaml`). The Dockerfile builds the React app, then runs FastAPI, which serves both the API and the UI.

To deploy your own copy:

1. Push this folder to a GitHub repository.
2. In Render, choose **New → Blueprint**, select the repository, and confirm. The free plan needs no payment details.
3. Render builds the image. The URL appears when the deploy finishes.

**Known limitation:** Render's free tier has no persistent disk, so the SQLite file is wiped whenever the service restarts, redeploys, or wakes up after ~15 minutes idle. The seed users and welcome document are recreated on startup, so the flows can always be demonstrated. I kept SQLite because it needs no paid service or extra account for reviewers; the next step would be a free hosted Postgres (e.g. Neon). See [ARCHITECTURE.md](ARCHITECTURE.md).

## Project layout

```
backend/
  app/main.py         documents, import, sharing, security middleware, serves the UI
  app/access.py       mocked auth + role checks (viewer < commenter < editor < owner)
  app/collab.py       version history, comments, presence
  app/content.py      HTML sanitizing + .txt/.md/.docx conversion
  app/db.py           SQLite schema, seed data, connection helper
  tests/              test_api.py, test_collab.py, conftest.py
frontend/src/
  App.jsx             layout, user switcher, routing (#/doc/:id)
  Sidebar.jsx         document lists + import
  DocumentEditor.jsx  Tiptap editor, autosave, conflicts, presence
  Toolbar.jsx         formatting buttons
  ShareDialog.jsx     share / change role / remove
  CommentsPanel.jsx   comments side panel
  HistoryPanel.jsx    version history side panel
  Presence.jsx        "who's here" avatars
  exportDoc.js        PDF (print) and Markdown export
```

## Other docs

- [ARCHITECTURE.md](ARCHITECTURE.md): what I prioritized and why
- [AI_WORKFLOW.md](AI_WORKFLOW.md): how I used AI tools
- [SUBMISSION.md](SUBMISSION.md): what's included
