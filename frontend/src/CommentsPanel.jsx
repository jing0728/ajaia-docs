import { useCallback, useEffect, useState } from "react";
import { api, ROLE_RANK, timeAgo } from "./api.js";

// Document-level comments. A comment can quote the text that was selected when it was
// written; clicking the quote selects that text again if it still exists.

function selectedText(editor) {
  if (!editor) return "";
  const { from, to } = editor.state.selection;
  return editor.state.doc.textBetween(from, to, " ").trim().slice(0, 500);
}

function findAndSelect(editor, quote) {
  let found = null;
  editor.state.doc.descendants((node, pos) => {
    if (found !== null || !node.isText) return found === null;
    const index = node.text.indexOf(quote);
    if (index >= 0) found = pos + index;
    return true;
  });
  if (found === null) return false;
  editor.chain().focus().setTextSelection({ from: found, to: found + quote.length }).scrollIntoView().run();
  return true;
}

export default function CommentsPanel({ docId, userId, role, editor, onCount, onClose }) {
  const [comments, setComments] = useState([]);
  const [draft, setDraft] = useState("");
  const [quote, setQuote] = useState("");
  const [showResolved, setShowResolved] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const canComment = ROLE_RANK[role] >= ROLE_RANK.commenter;
  const canModerate = ROLE_RANK[role] >= ROLE_RANK.editor;

  const load = useCallback(() => {
    api
      .listComments(docId, userId)
      .then((list) => {
        setComments(list);
        onCount(list.filter((c) => !c.resolved).length);
      })
      .catch((e) => setError(e.message));
  }, [docId, userId, onCount]);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000); // pick up other people's comments
    return () => clearInterval(id);
  }, [load]);

  // Offer the current selection as the quote whenever the selection changes.
  useEffect(() => {
    if (!editor) return;
    const update = () => {
      const text = selectedText(editor);
      if (text) setQuote(text);
    };
    update();
    editor.on("selectionUpdate", update);
    return () => editor.off("selectionUpdate", update);
  }, [editor]);

  async function submit(e) {
    e.preventDefault();
    if (!draft.trim()) return setError("Write something first.");
    setBusy(true);
    setError("");
    try {
      await api.addComment(docId, draft.trim(), quote || null, userId);
      setDraft("");
      setQuote("");
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function act(promise) {
    try {
      await promise;
      load();
    } catch (err) {
      setError(err.message);
    }
  }

  const open = comments.filter((c) => !c.resolved);
  const resolved = comments.filter((c) => c.resolved);

  function renderComment(c) {
    // Your own comments are yours to manage only while you can still comment
    // (someone downgraded to "View only" can't change them anymore).
    const mine = c.user_id === userId && canComment;
    return (
      <li key={c.id} className={c.resolved ? "comment resolved" : "comment"}>
        <div className="comment-head">
          <strong>{c.author}</strong>
          <span className="muted">{timeAgo(c.created_at)}</span>
        </div>
        {c.quote && (
          <button className="quote" title="Find this text in the document" onClick={() => findAndSelect(editor, c.quote) || setError("That text is no longer in the document.")}>
            “{c.quote}”
          </button>
        )}
        <p className="comment-body">{c.body}</p>
        <div className="comment-actions">
          {(mine || canModerate) && (
            <button className="link" onClick={() => act(api.setResolved(docId, c.id, !c.resolved, userId))}>
              {c.resolved ? "Reopen" : "Resolve"}
            </button>
          )}
          {(mine || role === "owner") && (
            <button className="link danger" onClick={() => act(api.deleteComment(docId, c.id, userId))}>Delete</button>
          )}
        </div>
      </li>
    );
  }

  return (
    <aside className="side-panel" aria-label="Comments">
      <div className="panel-head">
        <h2>Comments</h2>
        <button className="link" onClick={onClose} aria-label="Close comments">Close</button>
      </div>

      {canComment ? (
        <form className="comment-form" onSubmit={submit}>
          {quote ? (
            <div className="quote-chip">
              <span>On: “{quote.length > 80 ? quote.slice(0, 80) + "…" : quote}”</span>
              <button type="button" className="link" onClick={() => setQuote("")} aria-label="Don't quote the selection">✕</button>
            </div>
          ) : (
            <p className="hint">Tip: select text in the document first to comment on it.</p>
          )}
          <textarea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setError("");
            }}
            placeholder="Add a comment…"
            rows={3}
            maxLength={2000}
            aria-label="New comment"
          />
          <button className="primary" disabled={busy}>Comment</button>
        </form>
      ) : (
        <p className="hint">You have view-only access, so you can read comments but not add them.</p>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}

      {open.length === 0 && <p className="muted">No open comments.</p>}
      <ul className="comment-list">{open.map(renderComment)}</ul>

      {resolved.length > 0 && (
        <>
          <button className="link" onClick={() => setShowResolved((s) => !s)}>
            {showResolved ? "Hide" : "Show"} resolved ({resolved.length})
          </button>
          {showResolved && <ul className="comment-list">{resolved.map(renderComment)}</ul>}
        </>
      )}
    </aside>
  );
}
