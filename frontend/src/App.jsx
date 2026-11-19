import { useCallback, useEffect, useRef, useState } from "react";
import { api, setCurrentUser } from "./api.js";
import Sidebar from "./Sidebar.jsx";
import DocumentEditor from "./DocumentEditor.jsx";

// The open document lives in the URL hash (#/doc/12) so a refresh reopens it.
function docIdFromHash() {
  const match = window.location.hash.match(/^#\/doc\/(\d+)$/);
  return match ? Number(match[1]) : null;
}

function readSavedUser() {
  try {
    return Number(localStorage.getItem("ajaia-user")) || 1;
  } catch {
    return 1;
  }
}

export default function App() {
  const [users, setUsers] = useState([]);
  const [userId, setUserId] = useState(readSavedUser);
  const [docs, setDocs] = useState({ owned: [], shared: [] });
  const [docId, setDocId] = useState(docIdFromHash);
  const [error, setError] = useState("");
  const [newDocId, setNewDocId] = useState(null); // just created: focus its title

  setCurrentUser(userId);
  const userIdRef = useRef(userId);
  userIdRef.current = userId;
  const listRequest = useRef(0);

  useEffect(() => {
    api.listUsers().then(setUsers).catch((e) => setError(e.message));
    const onHash = () => setDocId(docIdFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const refreshDocs = useCallback(() => {
    const requestedFor = userIdRef.current;
    const requestNo = ++listRequest.current;
    api
      .listDocuments(requestedFor)
      // Only the newest request may update the list: an older, slower response (for a
      // previous user, or from before the latest save) would show stale data.
      .then((list) => requestNo === listRequest.current && setDocs(list))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(refreshDocs, [userId, refreshDocs]);

  function openDoc(id) {
    window.location.hash = id ? `#/doc/${id}` : "";
  }

  function switchUser(id) {
    try {
      localStorage.setItem("ajaia-user", String(id));
    } catch {
      /* storage blocked: the choice just won't survive a refresh */
    }
    // Close the open document in the same render as the switch; otherwise it would
    // briefly reopen as the new user, who may not have access to it.
    setDocId(null);
    setUserId(id);
    setError("");
    openDoc(null);
  }

  async function createDoc() {
    try {
      const doc = await api.createDocument("Untitled document");
      refreshDocs();
      setNewDocId(doc.id);
      openDoc(doc.id);
    } catch (e) {
      setError(e.message);
    }
  }

  async function importFile(file) {
    try {
      const doc = await api.importFile(file);
      refreshDocs();
      openDoc(doc.id);
    } catch (e) {
      setError(`Import failed: ${e.message}`);
    }
  }

  const me = users.find((u) => u.id === userId);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">A</span> Ajaia Docs
        </div>
        <label className="user-switch">
          <span>Signed in as</span>
          <select value={userId} onChange={(e) => switchUser(Number(e.target.value))}>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name} ({u.email})
              </option>
            ))}
          </select>
        </label>
      </header>

      {error && (
        <div className="banner error" role="alert">
          {error}
          <button className="link" onClick={() => setError("")}>Dismiss</button>
        </div>
      )}

      <div className="layout">
        <Sidebar
          docs={docs}
          activeId={docId}
          onOpen={openDoc}
          onCreate={createDoc}
          onImport={importFile}
          onError={setError}
        />
        <main className="main">
          {docId ? (
            <DocumentEditor
              key={`${userId}-${docId}`}
              docId={docId}
              userId={userId}
              me={me}
              users={users}
              isNew={docId === newDocId}
              onChanged={refreshDocs}
              onBackgroundError={setError}
              onClosed={() => {
                refreshDocs();
                openDoc(null);
              }}
            />
          ) : (
            <div className="empty">
              <h2>No document open</h2>
              <p>Pick a document on the left, create a new one, or import a .txt, .md or .docx file.</p>
              <button className="primary" onClick={createDoc}>New document</button>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
