# Architecture note

## Shape of the system

```
Browser (React + Tiptap)  ──HTTP/JSON, X-User-Id header──▶  FastAPI  ──▶  SQLite
   │  autosave (PATCH + version)                               │
   │  heartbeat every 5 s (presence + "has it changed?")       │
   └─────────────────────── serves built React app ────────────┘  (one deployable service)
```

- **Frontend:** React with [Tiptap](https://tiptap.dev), a ProseMirror-based editor. The document is saved as HTML.
- **Backend:** FastAPI with plain `sqlite3`. Tables: `users`, `documents`, `shares` (role per user), `document_versions`, `comments`, `presence`.
- **Code layout:**
  - `access.py`: who you are and what you may do.
  - `main.py`: documents, import, sharing.
  - `collab.py`: history, comments, presence.
  - `content.py`: sanitizing and file conversion.
- **Deploy:** one Docker image. FastAPI serves both `/api/*` and the built frontend, so there is one URL, no CORS setup, and one thing to deploy.

## What I prioritized, and why

1. **Correct access control on the server.**
   - **Roles:** there are four levels: `viewer < commenter < editor < owner`.
   - **One check:** every route on an existing document starts with `get_access()`. It returns the caller's role, or 404 if they have no access. Using 404 rather than 403 means document ids don't reveal which documents exist.
   - **One deliberate exception:** `DELETE /presence` ("I've left this document") skips the check. It can only delete the caller's own presence row, it has to work right after access was revoked, and it returns 204 either way.
   - **Rule checks:** each action then calls `require(role, minimum)`.
   - **Source of truth:** the UI also hides controls, but the server enforces every rule. This is the part with the most tests.
2. **Not losing people's work.**
   - **Optimistic concurrency:** each document has a `version`. A save must include the version it was based on, and the `UPDATE ... WHERE version = ?` fails if someone saved in between. The user then sees a banner instead of silently overwriting a collaborator. This is cheap (one column, one WHERE clause) and covers the most common way shared docs lose data.
   - **Saves go out as the right person:** each save is sent as the user who typed it, even if they switch accounts mid-save.
   - **Retries:** transient failures retry automatically. Leaving a document finishes its save in the background, and the user is told if that fails.
   - **Lost access:** if edit access is removed mid-edit, the editor locks and explains why.
   - **No stale reloads:** reopening a document waits for its own pending save.
   - **Warning on close:** the browser warns before closing while anything is unsaved or still saving.
3. **Safe handling of untrusted input.**
   - **Sanitized HTML:** documents are shown in other people's browsers, so all HTML is sanitized server-side with an allowlist (`nh3`). This covers both editor content and imported files.
   - **Uploads:**
     - Size is capped while the body is being received, so a chunked upload can't bypass the cap.
     - `.docx` files are checked for "zip bombs" before conversion.
     - Conversion runs in a worker thread, so it can't freeze other requests.
   - **Bounds:** ids and versions are bounded, and titles are stripped of invisible and control characters.
   - **Headers:** a Content-Security-Policy and anti-framing headers act as a second line of defense.
4. **A coherent editing experience.**
   - Toolbar active states and keyboard shortcuts.
   - Role badges, and owned and shared lists kept separate.
   - Clear save status and error messages.
   - A layout that works on a phone.

## Collaboration features: what they are, and what they deliberately aren't

| Feature | What I built | What I didn't, and why |
|---|---|---|
| Real-time indicators | Heartbeat every 5 s shows who else has the doc open. If someone saves and you have no unsaved edits, your view updates in place; otherwise you're told a newer version exists. | No simultaneous typing (needs CRDTs/OT plus websockets: days of work). No live cursors. Polling instead of websockets keeps one simple deploy and works on free hosting. |
| Comments | Document-level comments that can quote the selected text; click a quote to find it. Resolve/reopen, delete, with role rules. | Not anchored to a position: if the quoted text is edited, the link is lost. Anchoring needs comment marks in the document model, which is a bigger change. No suggestion mode. |
| Version history | One snapshot per editing burst (same person, within 60 s), so autosave doesn't flood history. Preview and restore; restore is itself a new version. A restore sends the snapshot version you previewed and is refused if that snapshot changed since. While a restore runs, every change to the document is blocked, toolbar and undo included. | No visual diff between versions. Snapshots store full HTML (simple, fine at this size; would move to diffs at scale). |
| Export | PDF via the browser print dialog with a print stylesheet; Markdown via Turndown. | No server-side PDF rendering (adds a heavy dependency). Underline has no Markdown equivalent and is dropped. |
| Roles | Viewer / commenter / editor / owner, enforced server-side. | No ownership transfer, no link sharing, no groups. |

## Other decisions and tradeoffs

| Decision | Why | Cost |
|---|---|---|
| Mocked auth (user switcher + `X-User-Id` header) | Lets reviewers test sharing in seconds without sign-up. Real auth adds no product signal for this exercise. | Anyone can act as any user. Replacing it means changing one function (`current_user`) to verify a session or JWT. |
| Store HTML, not ProseMirror JSON | Readable in the database, easy to sanitize with standard tools, and what imports produce. | Less structured for future position-anchored comments. |
| SQLite, no ORM | Small schema; plain SQL is easy to review. | Free hosting has no persistent disk, so the demo DB resets. Postgres would fix this. |
| Import creates a new document | Simplest clearly useful flow ("bring my existing notes in"). | No import-into-existing-doc or attachments. |

## Intentionally left out

- Real authentication and sign-up
- Simultaneous co-editing and live cursors
- Suggestion mode and position-anchored comments
- Images, tables and attachments
- Search and pagination of the document list

## Next 2-4 hours

1. **Persistent data in production:** move to managed Postgres so deployed data survives restarts.
2. **Frontend tests:** add Playwright tests for share → switch user → view-only, and for comment → resolve.
3. **Real login:** magic link or OAuth, replacing `current_user`.
4. **Anchored comments:** attach comments to text ranges with a Tiptap mark, so they follow edits.
