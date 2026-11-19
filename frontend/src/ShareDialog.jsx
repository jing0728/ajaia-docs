import { useEffect, useRef, useState } from "react";
import { api, ROLE_LABEL } from "./api.js";

const ROLES = ["editor", "commenter", "viewer"];

function RoleSelect({ value, onChange, label }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
      {ROLES.map((r) => (
        <option key={r} value={r}>{ROLE_LABEL[r]}</option>
      ))}
    </select>
  );
}

export default function ShareDialog({ doc, userId, me, users, isOwner, onChanged, onClose }) {
  const [shares, setShares] = useState([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("editor");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef(null);
  // The parent passes a new onClose function on every render; keep the latest in a ref so
  // the keyboard effect below runs once (re-running it would steal focus each render).
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    api.listShares(doc.id, userId).then(setShares).catch((e) => setError(e.message));
  }, [doc.id, userId]);

  // Keyboard: Escape closes, Tab stays inside the dialog, and focus goes back to
  // whatever opened the dialog when it closes.
  useEffect(() => {
    const opener = document.activeElement;
    const first = dialog.current.querySelector("input, select, button");
    first?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") return closeRef.current();
      if (e.key !== "Tab") return;
      const focusable = [...dialog.current.querySelectorAll("input, select, button, textarea")].filter((el) => !el.disabled);
      const [firstEl, lastEl] = [focusable[0], focusable[focusable.length - 1]];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, []);

  async function submit(e) {
    e.preventDefault();
    if (!email.trim()) return setError("Enter an email address.");
    setBusy(true);
    setError("");
    try {
      const added = await api.share(doc.id, email.trim(), role, userId);
      setShares((list) => [...list.filter((s) => s.id !== added.id), added].sort((a, b) => a.name.localeCompare(b.name)));
      setEmail("");
      onChanged(); // updates the "Shared with N" badge in the sidebar
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(share, newRole) {
    try {
      await api.share(doc.id, share.email, newRole, userId);
      setShares((list) => list.map((s) => (s.id === share.id ? { ...s, role: newRole } : s)));
    } catch (err) {
      setError(err.message);
    }
  }

  async function remove(share) {
    try {
      await api.unshare(doc.id, share.id, userId);
      setShares((list) => list.filter((s) => s.id !== share.id));
      onChanged();
    } catch (err) {
      setError(err.message);
    }
  }

  // People this doc could still be shared with, offered as suggestions.
  const suggestions = users.filter((u) => u.id !== doc.owner.id && !shares.some((s) => s.id === u.id));

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        ref={dialog}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="share-title"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id="share-title">{isOwner ? `Share “${doc.title}”` : "People with access"}</h2>

        {isOwner && (
          <form className="share-form" onSubmit={submit} noValidate>
            <input
              type="email"
              list="user-emails"
              placeholder="Email, e.g. bob@ajaia.test"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setError("");
              }}
              aria-label="Email to share with"
            />
            <datalist id="user-emails">
              {suggestions.map((u) => (
                <option key={u.id} value={u.email}>{u.name}</option>
              ))}
            </datalist>
            <RoleSelect value={role} onChange={setRole} label="Access level" />
            <button className="primary" disabled={busy}>Share</button>
          </form>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}

        <ul className="share-list">
          <li>
            <span>
              <strong>{doc.owner.name}</strong> {doc.owner.id === me?.id && "(you)"}
              <br />
              <span className="muted">{doc.owner.email}</span>
            </span>
            <span className="muted">Owner</span>
          </li>
          {shares.map((s) => (
            <li key={s.id}>
              <span>
                <strong>{s.name}</strong> {s.id === me?.id && "(you)"}
                <br />
                <span className="muted">{s.email}</span>
              </span>
              {isOwner ? (
                <span className="share-controls">
                  <RoleSelect value={s.role} onChange={(r) => changeRole(s, r)} label={`Access for ${s.name}`} />
                  <button className="link danger" onClick={() => remove(s)}>Remove</button>
                </span>
              ) : (
                <span className="muted">{ROLE_LABEL[s.role]}</span>
              )}
            </li>
          ))}
        </ul>
        {isOwner && (
          <p className="hint">
            <strong>Can edit</strong>: change the text and restore versions. <strong>Can comment</strong>: read and comment.{" "}
            <strong>View only</strong>: read. Demo accounts: alice@, bob@, carol@ajaia.test.
          </p>
        )}

        <div className="modal-footer">
          <button onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
