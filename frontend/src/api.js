// Thin wrapper around fetch. Every request carries a mock user's id in X-User-Id.
//
// Most calls use the globally selected user. Calls made by an open document pass its
// userId explicitly, so a save that finishes after the user switched accounts is still
// sent as the person who typed it.

let currentUserId = null;

export function setCurrentUser(id) {
  currentUserId = id;
}

async function request(path, { json, body, method = "GET", userId = currentUserId } = {}) {
  const headers = { "X-User-Id": String(userId) };
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }

  let res;
  try {
    res = await fetch(path, { method, headers, body });
  } catch {
    throw Object.assign(new Error("Can't reach the server. Check your connection."), { status: 0 });
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      // FastAPI returns either {detail: "text"} or {detail: [{msg: ...}]} for validation errors.
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) message = data.detail[0].msg;
    } catch {
      /* response had no JSON body */
    }
    throw Object.assign(new Error(message), { status: res.status });
  }
  return res.status === 204 ? null : res.json();
}

const doc = (id) => `/api/documents/${id}`;

export const api = {
  listUsers: () => request("/api/users"),
  listDocuments: (userId) => request("/api/documents", { userId }),
  createDocument: (title) => request("/api/documents", { method: "POST", json: { title } }),
  importFile: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/documents/import", { method: "POST", body: form });
  },

  // Calls made from an open document: always sent as that document's user.
  getDocument: (id, userId) => request(doc(id), { userId }),
  updateDocument: (id, fields, userId) => request(doc(id), { method: "PATCH", json: fields, userId }),
  deleteDocument: (id, userId) => request(doc(id), { method: "DELETE", userId }),

  listShares: (id, userId) => request(`${doc(id)}/shares`, { userId }),
  share: (id, email, role, userId) => request(`${doc(id)}/shares`, { method: "POST", json: { email, role }, userId }),
  unshare: (id, targetId, userId) => request(`${doc(id)}/shares/${targetId}`, { method: "DELETE", userId }),

  listVersions: (id, userId) => request(`${doc(id)}/versions`, { userId }),
  getVersion: (id, versionId, userId) => request(`${doc(id)}/versions/${versionId}`, { userId }),
  restoreVersion: (id, versionId, baseVersion, snapshotVersion, userId) =>
    request(`${doc(id)}/versions/${versionId}/restore`, {
      method: "POST",
      json: { base_version: baseVersion, snapshot_version: snapshotVersion },
      userId,
    }),

  listComments: (id, userId) => request(`${doc(id)}/comments`, { userId }),
  addComment: (id, body, quote, userId) => request(`${doc(id)}/comments`, { method: "POST", json: { body, quote }, userId }),
  setResolved: (id, commentId, resolved, userId) =>
    request(`${doc(id)}/comments/${commentId}`, { method: "PATCH", json: { resolved }, userId }),
  deleteComment: (id, commentId, userId) => request(`${doc(id)}/comments/${commentId}`, { method: "DELETE", userId }),

  heartbeat: (id, userId) => request(`${doc(id)}/presence`, { method: "POST", userId }),
  leave: (id, userId) => request(`${doc(id)}/presence`, { method: "DELETE", userId }),
};

export const ROLE_LABEL = {
  owner: "Owner",
  editor: "Can edit",
  commenter: "Can comment",
  viewer: "View only",
};

export const ROLE_RANK = { viewer: 0, commenter: 1, editor: 2, owner: 3 };

export function timeAgo(unixSeconds) {
  const s = Math.max(0, Date.now() / 1000 - unixSeconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(unixSeconds * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
