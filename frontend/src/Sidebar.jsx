import { useRef } from "react";
import { ROLE_LABEL } from "./api.js";

const ACCEPTED = [".txt", ".md", ".docx"];
const MAX_BYTES = 2 * 1024 * 1024;

function formatDate(sqliteUtc) {
  // SQLite datetime('now') is UTC without a "Z"; add it so the browser converts to local time.
  return new Date(sqliteUtc.replace(" ", "T") + "Z").toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function Sidebar({ docs, activeId, onOpen, onCreate, onImport, onError }) {
  const fileInput = useRef(null);

  function handleFile(e) {
    const file = e.target.files[0];
    e.target.value = ""; // allow picking the same file again
    if (!file) return;
    // Quick client-side check for fast feedback; the server validates again.
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED.includes(ext)) return onError(`"${file.name}" isn't supported. Use .txt, .md or .docx.`);
    if (file.size > MAX_BYTES) return onError(`"${file.name}" is larger than 2 MB.`);
    onImport(file);
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-actions">
        <button className="primary" onClick={onCreate}>+ New document</button>
        <button onClick={() => fileInput.current.click()}>Import file</button>
        <input ref={fileInput} type="file" accept={ACCEPTED.join(",")} hidden onChange={handleFile} />
        <p className="hint">Import supports .txt, .md and .docx (up to 2 MB). Each file becomes a new editable document.</p>
      </div>

      <section>
        <h3>My documents</h3>
        {docs.owned.length === 0 && <p className="muted">Nothing yet.</p>}
        <ul className="doc-list">
          {docs.owned.map((d) => (
            <li key={d.id}>
              <button className={d.id === activeId ? "doc active" : "doc"} onClick={() => onOpen(d.id)}>
                <span className="doc-title">{d.title}</span>
                <span className="doc-meta">
                  Edited {formatDate(d.updated_at)}
                  {d.share_count > 0 && <> · <span className="badge shared">Shared with {d.share_count}</span></>}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>Shared with me</h3>
        {docs.shared.length === 0 && <p className="muted">No one has shared a document with you.</p>}
        <ul className="doc-list">
          {docs.shared.map((d) => (
            <li key={d.id}>
              <button className={d.id === activeId ? "doc active" : "doc"} onClick={() => onOpen(d.id)}>
                <span className="doc-title">{d.title}</span>
                <span className="doc-meta">
                  From {d.owner_name} · <span className={`badge ${d.role}`}>{ROLE_LABEL[d.role]}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}
