# AI workflow note

> **Draft. Rewrite in your own words before submitting.** Every line must be true to what you did. Delete anything you can't explain in the walkthrough, and fill in the TODOs. Remove this box when done.

## Tools used

- **Claude Code (desktop app):** scoping, generating the backend, frontend, tests and deploy config, and driving a browser to run the UI flows.
- **Independent AI reviewers, in two rounds.** Each reviewer got only the code and the assignment, not the builder's reasoning, so they couldn't simply agree with it.
  - **Round 1 (2 reviewers):** one looked for bugs and security issues; the other acted as a hiring panel checking requirements against the docs.
  - **Round 2 (6 reviewers, each with one focus):**
    - Backend access control
    - Frontend state and autosave
    - Security
    - Fresh setup and deploy from the README alone
    - Hiring-panel grading
    - Hands-on testing in a real browser
- `TODO: any other tools you used (ChatGPT, Codex, Copilot, etc.)`

## Where AI materially sped things up

- **Boilerplate across many surfaces:** FastAPI routes, React components, Tiptap setup, Dockerfile, CSS. By hand this would have used most of the timebox.
- **Library knowledge:** Tiptap's extension API, `mammoth` for .docx conversion, `nh3` for HTML sanitization, Turndown for Markdown export.
- **Edge-case tests:**
  - The permission matrix across four roles.
  - A real minimal .docx built in code.
  - A .docx zip bomb.
  - A chunked upload with no Content-Length.

## What was changed or rejected

The first working builds had real bugs that only showed up under review. I treated every finding as a claim to check against the code, not as an instruction.

**Round 1:**

- **Edits saved as the wrong user.**
  - Both reviewers found this independently. If you typed and then switched accounts within 0.8 s, the final autosave was sent with the *new* user's id.
  - Result: the edit was either credited to the wrong person or silently dropped (404).
  - Fix: the editor sends its own user id with every save. Confirmed in the browser.
- **Loose ends:**
  - A false "someone else edited" conflict when you came back to a document quickly.
  - Endless retries after losing access.
  - Imported links erased on the first edit.

**Round 2:**

- **Opening a document counted as an edit.**
  - The installed Tiptap version's `setEditable()` fires an update event by default, so every open triggered a save.
  - Result: version numbers went up, other people got false conflicts, and viewers saw a wrong "your edit access was removed" banner.
  - Round 1 missed this. One reviewer found it by reading the library source, and I confirmed it there.
  - Fix: pass `emitUpdate = false`. Confirmed in the browser that the version no longer changes on open.
- **Upload size limit could be bypassed.**
  - My round-1 fix only checked the declared Content-Length, so a chunked upload was still received in full. I had claimed this was fixed when it wasn't; the reviewer caught the overclaim.
  - Fix: count bytes while the body is being received. Checked against the live server by streaming 50 MB: it stopped at 2.2 MB with a 413.
- **.docx zip bomb.**
  - A 153 KB file expanded to 150 MB, blocked the server for minutes, and was stored as a 157-million-character document.
  - Fix:
    - Check the uncompressed size before converting.
    - Run the conversion in a worker thread.
    - Cap the size of stored content.
- **Other fixes:**
  - Very large ids caused 500 errors.
  - A save that changed nothing still bumped the version.
  - A blank title restored the wrong value.
  - Markdown numbered lists turned into bullets.
  - The share dialog overflowed on a phone and didn't trap keyboard focus.
  - Starlette and Vite had CVEs, so I upgraded both.
**Round 3: an outside reviewer (Codex), given a written brief with claims to verify:**

- **Restore vs. autosave.** Text typed while a restore was running could later be autosaved on top of the restored version. Fix: a restore is now one exclusive step. Typing is paused, earlier edits must have saved first, and live updates wait until it finishes. Checked in the browser by typing during a restore: the typed text was ignored and the restore held.
- **Live update could move backwards.** Heartbeats could overlap, so a slow, older response could be applied after a newer one. Fix: heartbeats now run one at a time, and a version is applied only if it is newer than what's on screen.
- **Draft silently lost after a conflict.** The failed draft was dropped, so closing the tab gave no warning. Fix: the draft stays on screen with a "Copy my text" button, and the browser warns before closing. Checked in the browser.
- **Access changes not shown until the next save.** Fix: the heartbeat now returns your current role, so an editor locks within ~5 s of being downgraded or removed. Checked in the browser for both cases.
- **Backend:**
  - A user downgraded to viewer could still resolve or delete their own old comments. They now need at least commenter access, which matches the permission table.
  - A PATCH could store more than 1M characters, because sanitizing makes text longer. The size is now checked after sanitizing.
  - A save that changed nothing still bumped the version. It no longer does.
  - Markdown lists lost their start number.

**Round 4 (Codex re-review of the round-3 fixes):** the main fixes held, but the edge cases didn't:

- **Restore could bring back different content from the preview.**
  - The newest snapshot is updated in place while its author keeps typing. Previewing it, typing more, then restoring would restore the *new* text.
  - Codex reproduced this through the API. I reproduced it through the UI.
  - Fix: the restore request carries the snapshot version that was previewed, and the server refuses if the snapshot has changed since.
- **The toolbar could still change the document during a restore.** `setEditable(false)` only stops typing; Tiptap commands still run. Fix: a ProseMirror plugin refuses all document changes while a restore runs, and the toolbar is hidden.
- **Reopening a document didn't wait for a restore** still running, only for saves. Fix: restores are registered with the same "wait for this first" mechanism.
- **A page stayed stuck after edit access came back.** It now shows "Your edit access is back. Reload to continue editing", keeping the draft and the Copy button. Checked in the browser.
- **Doc wording:** the architecture note now names the one route that intentionally skips `get_access()`.

**Round 5 (Codex, third re-review):** three smaller edge cases, all fixed.

- **Restore failure after leaving the document.** If a restore failed after you had moved to another document, the error had nowhere to show. It now appears as an app-level message naming the document.
- **Access restored as View only.** If your access came back as View only after being removed, the page stayed on "no access". Without an unsaved draft, it now loads the current version read-only. With a draft, it keeps the draft and offers a reload. Checked in the browser.
- **Copying a draft left out the title.** "Copy my draft" now includes an unsaved title.

**Also found during the rounds:**

- **A bug in my own fix.** When I bounded the id parameters, I shared one `Path(...)` object across several parameters, and FastAPI used the first parameter's name for all of them. A new test caught it.
- **Tests that were wrong, not the code.**
  - A .docx fixture had no numbering definition.
  - A chunked-upload test assumed the test client streams; it buffers the whole body. I fixed the tests and checked the real behaviour against a live server.
- **Scope decisions:**
  - I did not build simultaneous co-editing (CRDTs plus websockets) or position-anchored comments. Both are multi-day features.
  - Presence uses 5-second polling, which keeps a single simple deploy.
  - `TODO: anything you pushed back on or rewrote yourself`

## How correctness was verified

- **Automated:** 23 pytest API tests across documents, sharing, import, history, comments and presence. Each runs on a fresh database.
- **Browser runs (driven by the AI agent; `TODO: repeat these yourself`):**
  - **Basics:** create, format, rename, reload; formatting is kept.
  - **Viewer sharing:** share with Bob as viewer; Bob sees it read-only.
  - **Two users at once:** Alice in one tab, Bob in another.
    - Each sees the other's avatar.
    - Bob's edit appears in Alice's tab within 5 s, with no reload.
  - **History:** restore an old version; the restore shows up as a new history entry.
  - **Commenter:** Carol can comment but has no toolbar.
  - **Errors and conflicts:**
    - Import .md, reject .png, reject an unknown email.
    - A forced concurrent save shows the conflict banner.
    - Switching user right after typing keeps the edit.
- **Code reading:** `TODO: which parts you read line by line (e.g. get_access/require, update_document, the autosave flush, record_version) and what you asked the AI to explain.`
