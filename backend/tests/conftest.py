"""Shared fixtures, trimmed from GAM's.

Tests go through real HTTP from the first commit: gecko-notes tests its routers by
calling handler functions directly, so its status codes, response models and auth layer
are largely unverified.

The secret is set before any app module is imported: app.config refuses a weak or
missing JWT_SECRET_KEY at import time.
"""

import json
import os
from pathlib import Path

os.environ.setdefault("JWT_SECRET_KEY", "test-only-secret-not-used-in-production")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from app.auth import UserCtx, current_user  # noqa: E402
from app.database import get_session  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

TEST_USER_ID = "user-under-test"
FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(name="engine")
def engine_fixture():
    """An in-memory database shared across connections (StaticPool), with foreign keys
    enforced as production enforces them — a project points at its shadow user, and a
    test engine that let that slide could not fail the way production fails."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session):
    """An unauthenticated client. Requests to a protected route get a real 401."""
    fastapi_app.dependency_overrides[get_session] = lambda: session
    with TestClient(fastapi_app) as client:
        yield client
    fastapi_app.dependency_overrides.clear()


def _as(user_id: str):
    return lambda: UserCtx(id=user_id, username=user_id)


@pytest.fixture(name="auth_client")
def auth_client_fixture(session):
    """Signed in by overriding the dependency. Tests about token verification build a
    real token instead (test_auth.py), so this override never hides a broken auth path."""
    fastapi_app.dependency_overrides[get_session] = lambda: session
    fastapi_app.dependency_overrides[current_user] = _as(TEST_USER_ID)
    with TestClient(fastapi_app) as client:
        yield client
    fastapi_app.dependency_overrides.clear()


@pytest.fixture(name="switch_user")
def switch_user_fixture():
    """Call with a user id to make the next requests come from that user."""
    def switch(user_id: str) -> None:
        fastapi_app.dependency_overrides[current_user] = _as(user_id)
    return switch


@pytest.fixture(name="siblings")
def siblings_fixture(monkeypatch):
    """GAM and Notes, faked. Every outbound request GVC makes goes here."""
    import httpx

    from app import outbound
    from app.config import settings
    from tests.fake_siblings import GAM, NOTES, FakeSiblings

    fake = FakeSiblings()
    monkeypatch.setattr(outbound, "TRANSPORT", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(settings, "gam_base_url", GAM)
    monkeypatch.setattr(settings, "notes_base_url", NOTES)
    return fake


@pytest.fixture(autouse=True)
def no_render_workers(monkeypatch, tmp_path):
    """No worker threads in tests, and renders written under the test's own directory.

    The app's lifespan starts the render queue, and TestClient runs the lifespan; a
    test that wants a render to happen calls `worker._run` itself, which is also the
    only way to assert on what it did.
    """
    from app.config import settings
    from app.render import worker

    monkeypatch.setattr(worker.queue, "start", lambda: None)
    monkeypatch.setattr(worker.queue, "enqueue", lambda job_id: None)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    # The assistant's queue, the same way: a test runs a turn with `worker._run`.
    from app.assistant import worker as assistant_worker

    monkeypatch.setattr(assistant_worker.queue, "start", lambda: None)
    monkeypatch.setattr(assistant_worker.queue, "enqueue", lambda job_id: None)


# ── media a render can really encode ─────────────────────────────────────────

import subprocess  # noqa: E402


def _make(path, *args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args, path], check=True)
    with open(path, "rb") as f:
        return f.read()


@pytest.fixture(scope="module")
def files(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    return {
        "picture": _make(str(d / "p.png"), "-f", "lavfi", "-i", "testsrc=size=1600x900", "-frames:v", "1"),
        "reel": _make(str(d / "r.mp4"), "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                      "-f", "lavfi", "-i", "sine=frequency=220", "-t", "20",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"),
        "song_a": _make(str(d / "a.mp3"), "-f", "lavfi", "-i", "sine=frequency=330", "-t", "30"),
        "song_b": _make(str(d / "b.mp3"), "-f", "lavfi", "-i", "sine=frequency=660", "-t", "30"),
        "speech": _make(str(d / "s.wav"), "-f", "lavfi", "-i", "sine=frequency=500", "-t", "1.5"),
    }


@pytest.fixture
def library(siblings, files):
    from tests.fake_siblings import gam_asset

    for key, kind, size in (("p", "image", None), ("r", "video", 20.0),
                            ("a", "audio", 30.0), ("b", "audio", 30.0)):
        asset = gam_asset(key, f"asset {key}", kind, file_url=f"/media/{key}.bin", size_bytes=1,
                          duration_seconds=size)
        siblings.assets[key] = asset
    siblings.media_files = {"/media/p.bin": files["picture"], "/media/r.bin": files["reel"],
                            "/media/a.bin": files["song_a"], "/media/b.bin": files["song_b"]}
    siblings.speech = files["speech"]
    return siblings


