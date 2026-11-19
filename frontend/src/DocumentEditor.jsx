import { useEffect, useRef, useState } from "react";
import { EditorContent, Extension, useEditor } from "@tiptap/react";
import { Plugin } from "@tiptap/pm/state";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Placeholder from "@tiptap/extension-placeholder";
import Link from "@tiptap/extension-link";
import { api, ROLE_LABEL, ROLE_RANK } from "./api.js";
import { downloadMarkdown, printAsPdf } from "./exportDoc.js";
import Toolbar from "./Toolbar.jsx";
import ShareDialog from "./ShareDialog.jsx";
import CommentsPanel from "./CommentsPanel.jsx";
import HistoryPanel from "./HistoryPanel.jsx";
import Presence from "./Presence.jsx";

const AUTOSAVE_DELAY_MS = 800;
const RETRY_DELAY_MS = 3000;
const HEARTBEAT_MS = 5000;

const STATUS_TEXT = {
  saved: "All changes saved",
  unsaved: "Unsaved changes…",
  saving: "Saving…",
  error: "Save failed — retrying…",
  conflict: "Not saved — newer version exists",
  blocked: "Not saved — no edit access",
};

// Saves and restores still running for a document after its editor closed (e.g. the
// user clicked away and back quickly). Opening a document waits for these first, so it
// never loads content older than its own last save or restore.
const inflightSaves = new Map();

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export default function DocumentEditor({ docId, userId, me, users, isNew, onChanged, onClosed, onBackgroundError }) {
  const [doc, setDoc] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState("saved");
  const [saveError, setSaveError] = useState("");
  const [stopReason, setStopReason] = useState(null); // "conflict" | "blocked" | null
  const [panel, setPanel] = useState(null); // "comments" | "history" | null
  const [showShare, setShowShare] = useState(false);
  const [others, setOthers] = useState([]); // other people with this doc open
  const [notice, setNotice] = useState(""); // short-lived info message
  const [commentCount, setCommentCount] = useState(0);

  // Autosave state lives in refs so timers, the editor's onUpdate callback (created once)
  // and the unmount cleanup always see current values.
  const version = useRef(null);
  const pending = useRef({}); // fields changed since the last successful save
  const timer = useRef(null);
  const inFlight = useRef(null); // promise of the save currently running, if any
  const mounted = useRef(true);
  const stopped = useRef(false); // set after a conflict / lost access: no more saves
  const lostEdits = useRef(false); // user typed after saving stopped
  const goodTitle = useRef(""); // last non-blank title, restored if the field is cleared
  const editorRef = useRef(null);
  const titleInput = useRef(null);

  const role = doc?.role;
  const locked = stopReason === "blocked" || stopReason === "revoked" || stopReason === "regranted";
  const canEdit = role && ROLE_RANK[role] >= ROLE_RANK.editor && !locked;
  const isOwner = role === "owner";
  const roleRef = useRef(null); // current role, readable from timers and callbacks
  roleRef.current = role;
  const restoring = useRef(false);
  const restoreRun = useRef(null); // promise of the restore currently running, if any
  const [busy, setBusy] = useState(false); // a restore is running: no typing meanwhile
  const stopReasonRef = useRef(null); // stopReason, readable from timers

  // While a restore runs, refuse every change to the document, whatever its source:
  // typing, toolbar buttons, keyboard shortcuts, undo. setEditable(false) alone only
  // stops typing; Tiptap commands can still change the document.
  const restoreLock = useRef(
    Extension.create({
      name: "restoreLock",
      addProseMirrorPlugins: () => [new Plugin({ filterTransaction: (tr) => !(restoring.current && tr.docChanged) })],
    })
  ).current;

  const hasPending = () => Object.keys(pending.current).length > 0;
  const safe = (fn) => (...args) => mounted.current && fn(...args);
  // Anything that could race with a save or a restore.
  const isBusy = () => hasPending() || !!inFlight.current || stopped.current || restoring.current;

  // ---------- saving ----------

  /**
   * Stop autosaving after a conflict (409) or lost access (403/404).
   * hadDraft: the user had changes that never reached the server. We remember that, so
   * the tab-close warning and the "couldn't be saved" notice still fire. The text itself
   * stays visible in the editor (read-only if access was lost) and can be copied.
   */
  function stopSaving(reason, hadDraft) {
    stopped.current = true;
    clearTimeout(timer.current);
    if (hadDraft || hasPending()) lostEdits.current = true;
    pending.current = {};
    setStopReasonBoth(reason);
    safe(setStatus)(reason);
    if (reason === "blocked") {
      editorRef.current?.setEditable(false, false);
      // Find out what access we still have (maybe view/comment, maybe none).
      api
        .getDocument(docId, userId)
        .then((d) => safe(setDoc)((old) => ({ ...old, role: d.role })))
        .catch(() => setStopReasonBoth("revoked"));
    }
  }

  function setStopReasonBoth(reason) {
    stopReasonRef.current = reason;
    safe(setStopReason)(reason);
  }

  function copyDraft() {
    // Title first: an unsaved rename is part of the draft too.
    const text = `${goodTitle.current}\n\n${editorRef.current?.getText() || ""}`;
    navigator.clipboard
      .writeText(text)
      .then(() => setNotice("Copied your text to the clipboard."))
      .catch(() => setNotice("Couldn't copy automatically. Select the text and copy it."));
  }

  /** Send pending changes. Returns a promise that settles when this save is done. */
  async function flush() {
    clearTimeout(timer.current);
    if (inFlight.current) {
      // One save at a time, otherwise the second would carry a stale version.
      await inFlight.current;
      return flush();
    }
    if (stopped.current || !hasPending()) return;

    const fields = pending.current;
    pending.current = {};
    safe(setStatus)("saving");
    const run = (async () => {
      try {
        const saved = await api.updateDocument(docId, { ...fields, base_version: version.current }, userId);
        version.current = saved.version;
        safe(setSaveError)("");
        safe(setStatus)(hasPending() ? "unsaved" : "saved");
        onChanged(); // refresh "Edited …" time and order in the sidebar
      } catch (e) {
        if (e.status === 409) stopSaving("conflict", true);
        else if (e.status === 403 || e.status === 404) stopSaving("blocked", true);
        else {
          pending.current = { ...fields, ...pending.current }; // keep the changes for the next try
          safe(setSaveError)(e.message);
          safe(setStatus)("error");
          if (mounted.current) timer.current = setTimeout(flush, RETRY_DELAY_MS);
        }
      } finally {
        inFlight.current = null;
      }
    })();
    inFlight.current = run;
    return run;
  }

  function queueSave(fields) {
    if (restoring.current) return; // the editor and title are read-only during a restore
    if (stopped.current) {
      lostEdits.current = true; // typed after a conflict: warn before the tab closes
      return;
    }
    pending.current = { ...pending.current, ...fields };
    setStatus("unsaved");
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, AUTOSAVE_DELAY_MS);
  }

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Underline,
      Link.configure({ openOnClick: false, autolink: true }),
      Placeholder.configure({ placeholder: "Start writing…" }),
      restoreLock,
    ],
    content: "",
    editable: false, // turned on once we know the user's role
    onUpdate: ({ editor }) => queueSave({ content: editor.getHTML() }),
  });
  editorRef.current = editor;

  // ---------- loading ----------

  useEffect(() => {
    let cancelled = false;
    Promise.resolve(inflightSaves.get(docId)) // wait for our own save from a moment ago
      .then(() => api.getDocument(docId, userId))
      .then((d) => {
        if (cancelled) return;
        setDoc(d);
        setTitle(d.title);
        goodTitle.current = d.title;
        version.current = d.version;
      })
      .catch((e) => !cancelled && setLoadError(e.status === 404 ? "This document doesn't exist or you don't have access to it." : e.message));
    return () => {
      cancelled = true;
    };
  }, [docId, userId]);

  // Put the content into the editor once both are ready.
  useEffect(() => {
    if (!editor || !doc) return;
    // Second argument false = don't fire an update event. Without it, merely opening a
    // document would look like an edit and trigger a save.
    editor.commands.setContent(doc.content, false);
    editor.setEditable(ROLE_RANK[doc.role] >= ROLE_RANK.editor, false);
    if (isNew) titleInput.current?.select();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, doc?.id]);

  useEffect(() => {
    if (title) document.title = `${title} – Ajaia Docs`;
    return () => {
      document.title = "Ajaia Docs";
    };
  }, [title]);

  // ---------- presence + picking up other people's saves ----------

  /** The owner changed our access while the document is open. */
  function applyRoleChange(newRole) {
    const couldEdit = ROLE_RANK[roleRef.current] >= ROLE_RANK.editor;
    const canNow = ROLE_RANK[newRole] >= ROLE_RANK.editor;
    roleRef.current = newRole;
    setDoc((d) => ({ ...d, role: newRole }));
    if (couldEdit && !canNow) {
      // Lock now rather than waiting for the next save to be refused.
      if (hasPending() || inFlight.current) stopSaving("blocked", true);
      else editorRef.current?.setEditable(false, false);
      setNotice(`Your access changed to “${ROLE_LABEL[newRole]}”.`);
    } else if (!couldEdit && canNow && !stopped.current) {
      editorRef.current?.setEditable(true, false);
      setNotice("You can now edit this document.");
    }
  }

  /** Unlock after access came back: show the server's current version with the new role. */
  async function resumeWithServerVersion() {
    const fresh = await api.getDocument(docId, userId);
    const ed = editorRef.current;
    ed.commands.setContent(fresh.content, false);
    version.current = fresh.version;
    goodTitle.current = fresh.title;
    setTitle(fresh.title);
    roleRef.current = fresh.role;
    setDoc((d) => ({ ...d, role: fresh.role }));
    stopped.current = false;
    setStopReasonBoth(null);
    setStatus("saved");
    ed.setEditable(ROLE_RANK[fresh.role] >= ROLE_RANK.editor, false);
    setNotice(`Your access is back: ${ROLE_LABEL[fresh.role]}.`);
  }

  useEffect(() => {
    if (!doc) return;
    let stop = false;
    let timerId;

    async function beat() {
      try {
        const r = await api.heartbeat(docId, userId);
        if (stop) return;
        setOthers(r.others);
        if (r.role !== roleRef.current) applyRoleChange(r.role);
        const wasLocked = stopReasonRef.current === "blocked" || stopReasonRef.current === "revoked";
        const regainedEditing = stopReasonRef.current === "blocked" && ROLE_RANK[r.role] >= ROLE_RANK.editor;
        if (stopReasonRef.current === "revoked" || regainedEditing) {
          // Access came back after we locked (any role if it had been removed entirely,
          // or edit rights if we'd been downgraded).
          if (lostEdits.current) {
            // There's an unsaved draft on screen: don't replace it. Keep it copyable and
            // let the user reload when ready.
            setDoc((d) => ({ ...d, role: r.role }));
            setStopReasonBoth("regranted");
          } else {
            // Nothing to lose: load the current version and carry on with the new role.
            await resumeWithServerVersion();
          }
          return;
        }
        if (wasLocked) return; // still downgraded: stay locked
        if (r.version <= version.current) return;

        const name = r.updated_by?.id === userId ? "your other tab" : r.updated_by?.name || "someone";
        if (isBusy()) {
          setNotice(`${name} saved a newer version.`);
          return;
        }
        // Nothing unsaved here, so it's safe to load their version in place.
        const fresh = await api.getDocument(docId, userId);
        // Re-check everything after the wait: we may have started typing, or something
        // newer may already be applied (never move the editor backwards).
        if (stop || isBusy() || fresh.version <= version.current) return;
        const ed = editorRef.current;
        const { from } = ed.state.selection;
        ed.commands.setContent(fresh.content, false);
        ed.commands.setTextSelection(Math.min(from, ed.state.doc.content.size));
        version.current = fresh.version;
        goodTitle.current = fresh.title;
        setTitle(fresh.title);
        setNotice(`Updated with ${name}'s changes.`);
        onChanged();
      } catch (e) {
        // 404: our access was removed. Keep the text on screen (read-only) and say so.
        const alreadyLocked = ["blocked", "revoked"].includes(stopReasonRef.current);
        if (e.status === 404 && !stop && !alreadyLocked) stopSaving("blocked", hasPending() || !!inFlight.current);
        /* other errors: presence is best-effort; the next beat will try again */
      }
    }

    // One heartbeat at a time: the next is scheduled only after this one finishes, so a
    // slow response can't arrive after a newer one and overwrite it.
    async function loop() {
      await beat();
      if (!stop) timerId = setTimeout(loop, HEARTBEAT_MS);
    }
    loop();
    return () => {
      stop = true;
      clearTimeout(timerId);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id, docId, userId]);

  useEffect(() => {
    if (!notice) return;
    const id = setTimeout(() => setNotice(""), 5000);
    return () => clearTimeout(id);
  }, [notice]);

  // ---------- leaving ----------

  useEffect(() => {
    mounted.current = true;
    const warn = (e) => {
      if (hasPending() || inFlight.current || lostEdits.current) {
        e.preventDefault();
        e.returnValue = ""; // needed by some browsers to show the prompt
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      mounted.current = false;
      api.leave(docId, userId).catch(() => {});
      // Finish saving in the background, retrying a couple of times on network errors,
      // and tell the user if it still didn't work.
      const drain = (async () => {
        await restoreRun.current; // a restore that's still running counts too
        for (let attempt = 1; attempt <= 3; attempt++) {
          await flush();
          if (!hasPending() || stopped.current) break;
          await sleep(1000 * attempt);
        }
        if (hasPending() || lostEdits.current) {
          onBackgroundError(`Some changes to “${goodTitle.current}” could not be saved.`);
        }
      })();
      inflightSaves.set(docId, drain);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ---------- actions ----------

  function onTitleChange(value) {
    setTitle(value);
    if (value.trim()) {
      goodTitle.current = value.trim();
      queueSave({ title: value.trim() });
    }
  }

  function onTitleBlur() {
    if (!title.trim()) setTitle(goodTitle.current); // blank titles aren't allowed; restore
  }

  async function remove() {
    if (!window.confirm(`Delete “${title}”? This can't be undone.`)) return;
    clearTimeout(timer.current);
    stopped.current = true; // don't autosave a document we're deleting
    try {
      await inFlight.current;
      await api.deleteDocument(docId, userId);
      pending.current = {};
      onClosed();
    } catch (e) {
      stopped.current = false; // delete failed: keep the edits and carry on saving
      setSaveError(e.message);
      if (hasPending()) timer.current = setTimeout(flush, AUTOSAVE_DELAY_MS);
    }
  }

  /**
   * Restore an old version. Runs as one exclusive step: typing is paused, everything
   * already typed must be saved first, and live updates wait until it's done. Otherwise
   * a queued autosave could overwrite the restored content, or the restore could wipe
   * text typed while it was running.
   */
  function restore(versionRow) {
    if (restoring.current) return Promise.resolve({ error: "A restore is already running." });
    // Register the restore so that reopening this document waits for it. If the user has
    // already left the document when it fails, the History panel is gone, so report the
    // failure at the app level instead.
    const docTitle = goodTitle.current;
    const run = runRestore(versionRow).then((result) => {
      if (result.error && !mounted.current) {
        onBackgroundError(`Restoring an earlier version of “${docTitle}” failed: ${result.error}`);
      }
      return result;
    });
    restoreRun.current = run;
    inflightSaves.set(docId, run);
    return run;
  }

  async function runRestore(versionRow) {
    restoring.current = true;
    setBusy(true);
    editor.setEditable(false, false);
    try {
      await flush(); // save anything typed just before restoring
      if (stopped.current) return { error: "Reload the document before restoring." };
      if (hasPending()) return { error: "Your latest changes couldn't be saved yet, so nothing was restored. Try again in a moment." };
      // versionRow.version: the snapshot as previewed. The server refuses if it has changed since.
      const restored = await api.restoreVersion(docId, versionRow.id, version.current, versionRow.version, userId);
      clearTimeout(timer.current);
      pending.current = {};
      restoring.current = false; // let this one change through the lock (same tick, nothing can interleave)
      editor.commands.setContent(restored.content, false);
      version.current = restored.version;
      goodTitle.current = restored.title;
      setTitle(restored.title);
      setStatus("saved");
      setNotice("Version restored. You can undo this from History.");
      onChanged();
      return {};
    } catch (e) {
      return { error: e.message };
    } finally {
      restoring.current = false;
      restoreRun.current = null;
      safe(setBusy)(false);
      if (!stopped.current) editorRef.current?.setEditable(ROLE_RANK[roleRef.current] >= ROLE_RANK.editor, false);
    }
  }

  function togglePanel(name) {
    setPanel((p) => (p === name ? null : name));
  }

  // ---------- render ----------

  if (loadError) {
    return (
      <div className="empty">
        <h2>Can't open document</h2>
        <p>{loadError}</p>
      </div>
    );
  }
  if (!doc) return <div className="empty muted">Loading…</div>;

  return (
    <div className={panel ? "doc-area with-panel" : "doc-area"}>
      <div className="editor-wrap">
        <div className="doc-header">
          <input
            ref={titleInput}
            className="title-input"
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            onBlur={onTitleBlur}
            onKeyDown={(e) => e.key === "Enter" && editor?.commands.focus("start")}
            disabled={!canEdit || busy}
            maxLength={200}
            aria-label="Document title"
          />
          <div className="doc-actions">
            <Presence others={others} />
            {canEdit && <span className={`status ${status}`}>{STATUS_TEXT[status]}</span>}
            {!isOwner && <span className={`badge ${role}`}>{ROLE_LABEL[role]}</span>}
            <button className={panel === "comments" ? "active" : ""} onClick={() => togglePanel("comments")}>
              Comments{commentCount ? ` (${commentCount})` : ""}
            </button>
            <button className={panel === "history" ? "active" : ""} onClick={() => togglePanel("history")}>History</button>
            <button onClick={() => setShowShare(true)}>{isOwner ? "Share" : "People"}</button>
            <details className="menu">
              <summary>Export</summary>
              <div className="menu-items" onClick={(e) => e.currentTarget.parentElement.removeAttribute("open")}>
                <button onClick={() => printAsPdf(title)}>PDF (print dialog)</button>
                <button onClick={() => downloadMarkdown(title, editor.getHTML())}>Markdown (.md)</button>
              </div>
            </details>
            {isOwner && <button className="danger" onClick={remove}>Delete</button>}
          </div>
        </div>
        <p className="owner-line muted">
          Owner: {isOwner ? "you" : `${doc.owner.name} (${doc.owner.email})`}
          {notice && <span className="notice" role="status"> · {notice}</span>}
        </p>

        {stopReason === "conflict" && (
          <div className="banner warn" role="alert">
            Someone else saved this document while you were editing, so your latest changes were not saved.
            Your text is still below.
            <button className="link" onClick={copyDraft}>Copy my draft</button>
            <button className="link" onClick={() => window.location.reload()}>Reload latest version</button>
          </div>
        )}
        {locked && (
          <div className="banner warn" role="alert">
            {stopReason === "revoked" && "You no longer have access to this document."}
            {stopReason === "blocked" && "Your edit access was removed while you were editing."}
            {stopReason === "regranted" && `Your access is back (${ROLE_LABEL[role]}). Reload to continue.`}{" "}
            {lostEdits.current && "Your latest changes were not saved; they're still shown below."}
            {lostEdits.current && <button className="link" onClick={copyDraft}>Copy my draft</button>}
            {stopReason === "regranted" && <button className="link" onClick={() => window.location.reload()}>Reload</button>}
          </div>
        )}
        {busy && <div className="banner warn" role="status">Restoring version… editing is paused.</div>}
        {saveError && !stopReason && <div className="banner error" role="alert">{saveError}</div>}

        {canEdit && !busy && <Toolbar editor={editor} />}
        <div className="page">
          <EditorContent editor={editor} />
        </div>
      </div>

      {panel === "comments" && (
        <CommentsPanel
          docId={docId}
          userId={userId}
          role={role}
          editor={editor}
          onCount={setCommentCount}
          onClose={() => setPanel(null)}
        />
      )}
      {panel === "history" && (
        <HistoryPanel
          docId={docId}
          userId={userId}
          canRestore={canEdit && !stopReason}
          currentVersion={version.current}
          onRestore={restore}
          onClose={() => setPanel(null)}
        />
      )}
      {/* Keep the comment count on the button fresh even with the panel closed. */}
      {panel !== "comments" && <CommentCounter docId={docId} userId={userId} onCount={setCommentCount} />}

      {showShare && (
        <ShareDialog
          doc={{ ...doc, title }}
          userId={userId}
          me={me}
          users={users}
          isOwner={isOwner}
          onChanged={onChanged}
          onClose={() => setShowShare(false)}
        />
      )}
    </div>
  );
}

function CommentCounter({ docId, userId, onCount }) {
  useEffect(() => {
    let stop = false;
    const load = () =>
      api.listComments(docId, userId).then((list) => !stop && onCount(list.filter((c) => !c.resolved).length)).catch(() => {});
    load();
    const id = setInterval(load, 15000);
    return () => {
      stop = true;
      clearInterval(id);
    };
  }, [docId, userId, onCount]);
  return null;
}
