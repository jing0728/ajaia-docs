import { useEffect, useState } from "react";
import { api, timeAgo } from "./api.js";

// Version history: one entry per editing burst (see collab.py). Pick an entry to preview
// it; editors can restore it. Restoring creates a new version, so it can be undone.

export default function HistoryPanel({ docId, userId, canRestore, currentVersion, onRestore, onClose }) {
  const [versions, setVersions] = useState([]);
  const [selected, setSelected] = useState(null); // full version incl. content
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listVersions(docId, userId).then(setVersions).catch((e) => setError(e.message));
  }, [docId, userId, currentVersion]);

  async function preview(v) {
    setError("");
    try {
      setSelected(await api.getVersion(docId, v.id, userId));
    } catch (e) {
      setError(e.message);
    }
  }

  async function restore() {
    if (!window.confirm("Replace the current document with this version? You can undo this from History.")) return;
    setBusy(true);
    const result = await onRestore(selected);
    setBusy(false);
    if (result.error) setError(result.error);
    else setSelected(null);
  }

  return (
    <aside className="side-panel" aria-label="Version history">
      <div className="panel-head">
        <h2>History</h2>
        <button className="link" onClick={onClose} aria-label="Close history">Close</button>
      </div>
      <p className="hint">A snapshot is kept for each editing session (saves by the same person within a minute are grouped).</p>
      {error && <p className="form-error" role="alert">{error}</p>}

      {selected ? (
        <div className="version-preview">
          <button className="link" onClick={() => setSelected(null)}>← All versions</button>
          <h3>{selected.title}</h3>
          <p className="muted">Saved {timeAgo(selected.created_at)}</p>
          {/* Safe to render: content is sanitized on the server before it is ever stored. */}
          <div className="preview-body" dangerouslySetInnerHTML={{ __html: selected.content }} />
          {canRestore && (
            <button className="primary" onClick={restore} disabled={busy || selected.version === currentVersion}>
              {selected.version === currentVersion ? "This is the current version" : "Restore this version"}
            </button>
          )}
        </div>
      ) : (
        <ul className="version-list">
          {versions.map((v, i) => (
            <li key={v.id}>
              <button className="version" onClick={() => preview(v)}>
                <span>
                  <strong>{timeAgo(v.created_at)}</strong>
                  {i === 0 && <span className="badge shared">Current</span>}
                </span>
                <span className="muted">
                  {v.saved_by_name}
                  {v.note ? ` · ${v.note}` : ""}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
