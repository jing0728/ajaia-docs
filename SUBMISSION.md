# Submission

| Item | Where |
|---|---|
| Live app | https://ajaia-docs-fjpk.onrender.com |
| Walkthrough video | `VIDEO_URL.txt` |
| Source code | `backend/`, `frontend/`, `Dockerfile`, `render.yaml`, `.dockerignore`, `.gitignore` |
| Setup and run instructions | `README.md` |
| Architecture note | `ARCHITECTURE.md` |
| AI workflow note | `AI_WORKFLOW.md` |
| Automated tests | `backend/tests/` (`test_api.py`, `test_collab.py`, `conftest.py`) + `backend/pytest.ini`. 23 tests; see README → Tests. |

## Test accounts

No passwords. Choose a user from **Signed in as** at the top right:
`alice@ajaia.test`, `bob@ajaia.test`, `carol@ajaia.test`.

A fresh database includes *Welcome to Ajaia Docs*. Alice owns it, Bob can edit it, and Carol can comment on it. It already has one comment and a version history.

## Status

**Working end to end:**

- **Documents:** create, rename, edit, autosave and reopen.
- **Rich text:** bold, italic, underline, strike, H1–H3, bulleted and numbered lists, quotes and links.
- **Import:** .txt, .md and .docx files become new documents.
- **Sharing:**
  - By email, as editor, commenter or viewer, with role changes and removal.
  - Owned and shared documents are listed separately.
  - The server enforces every access rule.

**Stretch features (all five optional ones):**

- **Real-time indicators:** presence avatars and live update when someone else saves.
- **Comments:** quote selected text, resolve or reopen, delete.
- **Version history:** preview and restore.
- **Export:** PDF and Markdown.
- **Roles:** a commenter role, beyond basic view and edit access.

**Incomplete / limitations:**

- Authentication is mocked.
- There is no simultaneous co-editing; the second editor to save gets a conflict notice.
- Comments are not anchored to text positions.
- There are no automated frontend tests.
- Imported images and tables are not kept.
- The hosted SQLite database resets when the free Render instance restarts or wakes from idle (after about 15 minutes).

**Next 2-4 hours:**

- Postgres, so hosted data survives restarts.
- Playwright tests for the main flows.
- Real login.
- Comments anchored to text positions.
