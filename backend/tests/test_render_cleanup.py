"""`python -m app.render.cleanup`: render rows whose video is gone, listed, then removed."""

import shutil

import pytest

from app import database
from app.models.render import RenderJob
from app.render import cleanup, worker
from tests.test_renders_api import _finished, _project, _start


@pytest.fixture
def renders(auth_client, session, engine, monkeypatch):
    """Four renders: one with its video, two whose files went with a rebuild (one of
    them saved to GAM first), and one that failed and never had a file."""
    monkeypatch.setattr(database, "engine", engine)
    _, kept = _finished(auth_client, session)
    _, lost = _finished(auth_client, session)
    _, saved = _finished(auth_client, session)
    for job in (lost, saved):
        (worker.renders_dir() / job["id"] / "video.mp4").unlink()
    session.get(RenderJob, saved["id"]).gam_asset_id = "gam-9"
    failed = _start(auth_client, _project(auth_client)["id"]).json()["data"]
    row = session.get(RenderJob, failed["id"])
    row.status = "error"
    session.commit()
    return {"kept": kept["id"], "lost": lost["id"], "saved": saved["id"], "failed": failed["id"]}


def ids(session):
    session.expire_all()
    return {job.id for job in session.query(RenderJob).all()}


def test_by_default_it_only_lists(renders, session, capsys):
    assert cleanup.main([]) == 0
    out = capsys.readouterr().out
    assert "1 finished render(s) have their video; 2 do not." in out
    assert renders["lost"] in out and f"{renders['saved']}" in out and "saved to GAM as gam-9" in out
    assert renders["kept"] not in out and renders["failed"] not in out
    assert "Nothing deleted" in out
    assert ids(session) == set(renders.values())


def test_with_apply_it_deletes_only_the_orphans_and_their_leftovers(renders, session, capsys):
    poster = worker.renders_dir() / renders["lost"] / "poster.jpg"
    poster.write_bytes(b"x")
    assert cleanup.main(["--apply"]) == 0
    assert "Deleted 2 row(s)." in capsys.readouterr().out
    assert ids(session) == {renders["kept"], renders["failed"]}
    assert not poster.parent.exists()
    assert (worker.renders_dir() / renders["kept"] / "video.mp4").is_file()


def test_when_no_render_has_its_video_it_says_to_check_the_directory(renders, capsys):
    shutil.rmtree(worker.renders_dir())
    cleanup.main([])
    out = capsys.readouterr().out
    assert "0 finished render(s) have their video; 3 do not." in out
    assert "check the renders directory" in out
