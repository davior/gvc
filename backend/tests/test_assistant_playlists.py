"""The assistant and GAM's playlists: reading them, and proposing changes made by a button.

Reading is a look, like a search. A change (a new playlist, items added or taken out) is
GAM's and the user's, so it is proposed and made only when the person presses its button,
with their token, as a note is. It never touches the video.
"""

import json

from app.assistant import tools as T
from app.assistant import worker
from app.assistant.tools import Working
from app.config import settings
from app.gam.client import GamClient
from app.providers.base import ToolCall
from tests.fake_provider import call, says
from tests.fake_siblings import GAM, gam_asset, gam_playlist, playlist_item
from tests.test_assistant_turns import engine_for_worker, provider, start  # noqa: F401 - fixtures

TOKEN = {"Authorization": "Bearer user-token"}


def run(w, tool, **args):
    return T.execute(w, ToolCall(id="c1", name=tool, arguments=args))


def library(siblings):
    siblings.assets.update({
        "v1": gam_asset("v1", "Interview", duration_seconds=1800.0),
        "v2": gam_asset("v2", "Street", duration_seconds=60.0),
        "i1": gam_asset("i1", "Map", "image"),
        "d1": gam_asset("d1", "Report", "document"),
    })
    first = playlist_item("v1", start=62.0, end=101.5, label="On the bailout")
    first["id"] = "it-1"
    picture = playlist_item("i1", "image", image_seconds=3.0)
    picture["id"] = "it-2"
    siblings.playlists = {
        "p1": gam_playlist("p1", "The financial crisis", [first, picture],
                           description="Everyone on 2008."),
        "p2": gam_playlist("p2", "River", []),
    }


def working(siblings, **extra):
    library(siblings)
    return Working({"title": "x"}, gam=GamClient("t"), can_playlist=True, **extra)


def test_playlist_changes_are_offered_only_with_a_token_and_a_library():
    names = lambda w: {s.name for s in T.specs_for(w)}  # noqa: E731
    assert "propose_playlist" not in names(Working({"title": "x"}, gam=GamClient(None)))
    assert "propose_playlist" not in names(Working({"title": "x"}, can_playlist=True))
    assert "propose_playlist" in names(Working({"title": "x"}, gam=GamClient(None), can_playlist=True))
    assert {"search_playlists", "read_playlist"} <= T.READS


def test_playlists_are_searched_and_read_in_order_with_their_trims(siblings):
    w = working(siblings)
    found = json.loads(run(w, "search_playlists", query="2008").content)
    assert [p["playlist_id"] for p in found["playlists"]] == ["p1"]

    read = json.loads(run(w, "read_playlist", playlist_id="p1").content)
    bailout, picture = read["items"]
    assert (bailout["n"], bailout["item_id"], bailout["gam_id"]) == (1, "it-1", "v1")
    assert bailout["trim"] == {"in": 62.0, "out": 101.5} and bailout["label"] == "On the bailout"
    assert picture["seconds"] == 3.0 and "trim" not in picture
    # Known to set_visual by name, without a moment it would grow into whole sentences.
    assert w.hits["v1"].name == "Asset v1" and w.hits["v1"].start is None
    assert run(w, "read_playlist", playlist_id="nope").is_error


def test_a_long_playlist_is_read_in_pages(siblings):
    w = working(siblings)
    siblings.playlists["p2"] = gam_playlist(
        "p2", "Long", [playlist_item("v2", start=float(n), end=float(n) + 1) for n in range(60)])
    page = json.loads(run(w, "read_playlist", playlist_id="p2").content)
    assert len(page["items"]) == T.PLAYLIST_PAGE and "start 51" in page["more"]
    rest = json.loads(run(w, "read_playlist", playlist_id="p2", start=51).content)
    assert [i["n"] for i in rest["items"]] == list(range(51, 61)) and "more" not in rest


def test_a_proposal_is_checked_and_held_apart_from_the_video(siblings):
    w = working(siblings)
    ok = run(w, "propose_playlist", name="Picks", description="For the edit", add=[
        {"gam_id": "v1", "start_seconds": 5, "end_seconds": 9, "label": "Opening"},
        {"gam_id": "i1", "seconds": 4}])
    assert not ok.is_error, ok.content
    # The same new playlist again adds to the one proposal.
    run(w, "propose_playlist", name="picks", add=[{"gam_id": "v2"}])
    (entry,) = w.playlists
    assert w.changes == [] and entry["playlist_id"] is None and entry["state"] == "pending"
    assert [i["asset_id"] for i in entry["add"]] == ["v1", "i1", "v2"]
    assert (entry["add"][0]["in_point"], entry["add"][0]["out_point"]) == (5.0, 9.0)
    assert entry["add"][1]["image_seconds"] == 4.0 and "in_point" not in entry["add"][2]
    assert siblings.playlist_writes == []

    refusals = [
        dict(name="X", add=[{"gam_id": "d1"}]),                                  # a document
        dict(name="X", add=[{"gam_id": "nope"}]),                                # invented
        dict(name="X", add=[{"gam_id": "v2", "start_seconds": 10}]),             # half a range
        dict(name="X", add=[{"gam_id": "v2", "start_seconds": 50, "end_seconds": 70}]),  # past the end
        dict(name="X", add=[{"gam_id": "i1", "start_seconds": 0, "end_seconds": 1}]),    # picture range
        dict(name="X", remove=["it-1"]),                                         # new: nothing to remove
        dict(playlist_id="p1", remove=["not-an-item"]),
        dict(playlist_id="nope", add=[{"gam_id": "v1"}]),
        dict(),
    ]
    for args in refusals:
        assert run(w, "propose_playlist", **args).is_error, args
    assert len(w.playlists) == 1


def ask_to_change(auth_client, provider, monkeypatch, *calls):
    real_submit = worker.submit
    monkeypatch.setattr(worker, "submit",
                        lambda *a, **k: real_submit(*a, **{**k, "token": "turn-token"}))
    provider.script += [says("", *calls), says("Proposed; press the button to make it.")]
    turn = start(auth_client, prompt="Sort out my crisis playlist")
    worker._run(turn["id"])
    return auth_client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]


def test_a_change_to_a_playlist_is_made_by_its_button_once(
        auth_client, provider, siblings, engine_for_worker, monkeypatch):
    library(siblings)
    done = ask_to_change(auth_client, provider, monkeypatch,
                         call("read_playlist", playlist_id="p1"),
                         call("propose_playlist", playlist_id="p1", remove=["it-2"],
                              add=[{"gam_id": "v2", "start_seconds": 1, "end_seconds": 4}]))
    (proposal,) = done["playlists"]
    assert done["proposed_spec"] is None and done["outcome"] == ""
    assert proposal["name"] == "The financial crisis" and proposal["remove"][0]["item_id"] == "it-2"
    assert proposal["state"] == "pending" and siblings.playlist_writes == []

    url = f"/api/assistant/turns/{done['id']}/playlists/{proposal['playlist_ref']}"
    made = auth_client.post(f"{url}/apply", headers=TOKEN)
    assert made.status_code == 200, made.text
    (after,) = made.json()["data"]["playlists"]
    assert after["state"] == "applied" and after["skipped"] == []
    assert after["playlist_url"] == f"{settings.gam_base_url.rstrip('/')}/playlists/p1"
    # Added first (all or none), then taken out; both as the person who pressed.
    assert [(k, a) for k, _, a in siblings.playlist_writes] == [
        ("add", "Bearer user-token"), ("remove", "Bearer user-token")]
    items = siblings.playlists["p1"]["items"]
    assert [(i["asset_id"], i["start"], i["end"]) for i in items] == [
        ("v1", 62.0, 101.5), ("v2", 1.0, 4.0)]

    assert auth_client.post(f"{url}/apply", headers=TOKEN).status_code == 409
    assert len(siblings.playlist_writes) == 2


def test_a_new_playlist_is_made_and_a_refusal_leaves_it_pending(
        auth_client, provider, siblings, engine_for_worker, monkeypatch):
    library(siblings)
    done = ask_to_change(auth_client, provider, monkeypatch,
                         call("propose_playlist", name="Streets", add=[{"gam_id": "v2"}]))
    (proposal,) = done["playlists"]
    url = f"/api/assistant/turns/{done['id']}/playlists/{proposal['playlist_ref']}"

    # The asset went between the proposal and the button: GAM refuses, nothing is made.
    del siblings.assets["v2"]
    refused = auth_client.post(f"{url}/apply", headers=TOKEN)
    assert refused.status_code == 400 and refused.json()["detail"]["message"] == "No such asset."
    assert auth_client.get(f"/api/assistant/turns/{done['id']}").json()["data"][
        "playlists"][0]["state"] == "pending"

    siblings.assets["v2"] = gam_asset("v2", "Street")
    made = auth_client.post(f"{url}/apply", headers=TOKEN).json()["data"]["playlists"][0]
    new_id = made["playlist_id"]
    assert made["state"] == "applied" and siblings.playlists[new_id]["name"] == "Streets"
    assert made["playlist_url"] == f"{GAM}/playlists/{new_id}"


def test_an_item_already_gone_is_skipped_and_a_proposal_can_be_discarded(
        auth_client, provider, siblings, engine_for_worker, monkeypatch):
    library(siblings)
    done = ask_to_change(auth_client, provider, monkeypatch,
                         call("propose_playlist", playlist_id="p1", remove=["it-1"]),
                         call("propose_playlist", name="Other", add=[{"gam_id": "v1"}]))
    first, other = done["playlists"]
    siblings.playlists["p1"]["items"] = siblings.playlists["p1"]["items"][1:]

    base = f"/api/assistant/turns/{done['id']}/playlists"
    made = auth_client.post(f"{base}/{first['playlist_ref']}/apply", headers=TOKEN).json()["data"]
    assert made["playlists"][0]["skipped"] == ["On the bailout: already gone from the playlist."]

    gone = auth_client.post(f"{base}/{other['playlist_ref']}/discard").json()["data"]
    assert gone["playlists"][1]["state"] == "discarded"
    assert [k for k, _, _ in siblings.playlist_writes] == ["remove"]
    assert auth_client.post(f"{base}/nope/apply", headers=TOKEN).status_code == 404
