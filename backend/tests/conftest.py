import pytest
from fastapi.testclient import TestClient

ALICE, BOB, CAROL = {"X-User-Id": "1"}, {"X-User-Id": "2"}, {"X-User-Id": "3"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A test client on a fresh, empty SQLite file (seed users only, no demo docs)."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SEED_DEMO_DOCS", "0")
    from app.main import app

    with TestClient(app) as c:  # "with" runs the lifespan, which creates tables + seeds users
        yield c


def create_doc(client, headers, title="Plan", content="<p>hello</p>"):
    r = client.post("/api/documents", json={"title": title, "content": content}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def share(client, doc_id, email, role):
    r = client.post(f"/api/documents/{doc_id}/shares", json={"email": email, "role": role}, headers=ALICE)
    assert r.status_code == 201, r.text
