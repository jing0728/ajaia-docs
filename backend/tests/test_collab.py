"""Tests for version history, comments, commenter role, and presence."""

import time

from conftest import ALICE, BOB, CAROL, create_doc, share


def save(client, doc_id, headers, base_version, **fields):
    return client.patch(f"/api/documents/{doc_id}", json={"base_version": base_version, **fields}, headers=headers)


def test_versions_are_grouped_per_editing_burst_and_restorable(client, monkeypatch):
    doc = create_doc(client, ALICE, content="<p>v1</p>")
    url = f"/api/documents/{doc['id']}"
    share(client, doc["id"], "bob@ajaia.test", "editor")

    # Alice autosaves three times in a row: still one snapshot after "Created".
    v = doc["version"]
    for text in ("a", "ab", "abc"):
        v = save(client, doc["id"], ALICE, v, content=f"<p>{text}</p>").json()["version"]
    versions = client.get(f"{url}/versions", headers=ALICE).json()
    assert [x["note"] for x in versions] == [None, "Created"]
    assert client.get(f"{url}/versions/{versions[0]['id']}", headers=ALICE).json()["content"] == "<p>abc</p>"

    # A save by someone else starts a new snapshot.
    v = save(client, doc["id"], BOB, v, content="<p>bob rewrote it</p>").json()["version"]
    versions = client.get(f"{url}/versions", headers=ALICE).json()
    assert [x["saved_by_name"] for x in versions] == ["Bob Martinez", "Alice Chen", "Alice Chen"]

    # Restore Alice's version: content comes back, and the restore is itself a new version.
    alice_version = versions[1]
    restore = {"base_version": v, "snapshot_version": alice_version["version"]}
    r = client.post(f"{url}/versions/{alice_version['id']}/restore", json=restore, headers=ALICE)
    assert r.status_code == 200
    assert r.json()["content"] == "<p>abc</p>"
    assert r.json()["version"] == v + 1
    assert client.get(f"{url}/versions", headers=ALICE).json()[0]["note"].startswith("Restored")

    # A stale restore is rejected like a stale save.
    r = client.post(f"{url}/versions/{alice_version['id']}/restore", json=restore, headers=ALICE)
    assert r.status_code == 409


def test_restore_refuses_a_snapshot_that_changed_after_preview(client):
    doc = create_doc(client, ALICE, content="<p>start</p>")
    url = f"/api/documents/{doc['id']}"
    v = save(client, doc["id"], ALICE, 1, content="<p>Previewed</p>").json()["version"]
    previewed = client.get(f"{url}/versions", headers=ALICE).json()[0]
    assert client.get(f"{url}/versions/{previewed['id']}", headers=ALICE).json()["content"] == "<p>Previewed</p>"

    # Alice keeps typing within a minute, so the same snapshot row is updated in place.
    v = save(client, doc["id"], ALICE, v, content="<p>Subsequent edit</p>").json()["version"]
    assert client.get(f"{url}/versions", headers=ALICE).json()[0]["id"] == previewed["id"]

    # Restoring what she previewed must not silently restore something else.
    r = client.post(
        f"{url}/versions/{previewed['id']}/restore",
        json={"base_version": v, "snapshot_version": previewed["version"]},
        headers=ALICE,
    )
    assert r.status_code == 409
    assert "Preview it again" in r.json()["detail"]


def test_version_permissions(client):
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}"
    share(client, doc["id"], "bob@ajaia.test", "viewer")
    vid = client.get(f"{url}/versions", headers=ALICE).json()[0]["id"]

    assert client.get(f"{url}/versions", headers=BOB).status_code == 200  # viewers can see history
    assert client.post(f"{url}/versions/{vid}/restore", json={"base_version": 1, "snapshot_version": 1}, headers=BOB).status_code == 403
    assert client.get(f"{url}/versions", headers=CAROL).status_code == 404
    # A version id from another document is not reachable through this one.
    other = create_doc(client, CAROL)
    other_vid = client.get(f"/api/documents/{other['id']}/versions", headers=CAROL).json()[0]["id"]
    assert client.get(f"{url}/versions/{other_vid}", headers=ALICE).status_code == 404


def test_commenter_can_comment_but_not_edit(client):
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}"
    share(client, doc["id"], "carol@ajaia.test", "commenter")
    share(client, doc["id"], "bob@ajaia.test", "viewer")

    assert client.get(url, headers=CAROL).json()["role"] == "commenter"
    assert save(client, doc["id"], CAROL, 1, content="<p>x</p>").status_code == 403

    r = client.post(f"{url}/comments", json={"body": "Typo here", "quote": "hello"}, headers=CAROL)
    assert r.status_code == 201
    comment = r.json()
    assert comment["author"] == "Carol Singh" and comment["quote"] == "hello" and comment["resolved"] is False

    # Viewers can read comments but not add them; blank comments are rejected.
    assert len(client.get(f"{url}/comments", headers=BOB).json()) == 1
    assert client.post(f"{url}/comments", json={"body": "hi"}, headers=BOB).status_code == 403
    assert client.post(f"{url}/comments", json={"body": "   "}, headers=CAROL).status_code == 422


def test_comment_resolve_and_delete_rules(client):
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}"
    share(client, doc["id"], "bob@ajaia.test", "editor")
    share(client, doc["id"], "carol@ajaia.test", "commenter")
    bobs = client.post(f"{url}/comments", json={"body": "from bob"}, headers=BOB).json()
    carols = client.post(f"{url}/comments", json={"body": "from carol"}, headers=CAROL).json()

    # Commenters can only resolve their own; editors can resolve anyone's.
    assert client.patch(f"{url}/comments/{bobs['id']}", json={"resolved": True}, headers=CAROL).status_code == 403
    assert client.patch(f"{url}/comments/{carols['id']}", json={"resolved": True}, headers=CAROL).json()["resolved"]
    assert client.patch(f"{url}/comments/{carols['id']}", json={"resolved": False}, headers=BOB).status_code == 200

    # Only the author or the owner can delete.
    assert client.delete(f"{url}/comments/{carols['id']}", headers=BOB).status_code == 403
    assert client.delete(f"{url}/comments/{carols['id']}", headers=ALICE).status_code == 204
    assert client.delete(f"{url}/comments/{bobs['id']}", headers=BOB).status_code == 204
    assert client.get(f"{url}/comments", headers=ALICE).json() == []


def test_downgraded_author_cannot_change_own_comment(client):
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}"
    share(client, doc["id"], "carol@ajaia.test", "commenter")
    mine = client.post(f"{url}/comments", json={"body": "mine"}, headers=CAROL).json()

    share(client, doc["id"], "carol@ajaia.test", "viewer")  # Alice downgrades Carol
    assert client.patch(f"{url}/comments/{mine['id']}", json={"resolved": True}, headers=CAROL).status_code == 403
    assert client.delete(f"{url}/comments/{mine['id']}", headers=CAROL).status_code == 403


def test_presence_shows_who_else_is_here(client, monkeypatch):
    doc = create_doc(client, ALICE)
    url = f"/api/documents/{doc['id']}/presence"
    share(client, doc["id"], "bob@ajaia.test", "editor")

    assert client.post(url, headers=ALICE).json()["others"] == []
    r = client.post(url, headers=BOB).json()
    assert [o["name"] for o in r["others"]] == ["Alice Chen"]
    assert r["version"] == 1
    assert r["role"] == "editor"

    # The heartbeat reports a role change immediately, so an open editor can lock itself.
    share(client, doc["id"], "bob@ajaia.test", "viewer")
    assert client.post(url, headers=BOB).json()["role"] == "viewer"
    share(client, doc["id"], "bob@ajaia.test", "editor")

    # After Bob saves, Alice's heartbeat reports the new version and who saved it.
    save(client, doc["id"], BOB, 1, content="<p>new</p>")
    r = client.post(url, headers=ALICE).json()
    assert r["version"] == 2 and r["updated_by"]["name"] == "Bob Martinez"

    # Leaving removes you; people who stopped sending heartbeats drop off after 30 s.
    client.delete(url, headers=BOB)
    assert client.post(url, headers=ALICE).json()["others"] == []
    client.post(url, headers=BOB)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 31)
    assert client.post(url, headers=ALICE).json()["others"] == []

    # No access, no presence.
    assert client.post(url, headers=CAROL).status_code == 404
