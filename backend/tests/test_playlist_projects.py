"""A video started from a GAM playlist (gam#70): read as the caller, laid out, copied.

GAM keeps each item as an asset plus a range on its file, which is a GAM asset ref and a
`trim` here, so these check the placing: a moment of video is a clip with its own sound,
an image a held scene, a sound a scene with the sound anchored to it.
"""

from app.render.compile import Media, plan_units, unit_duration
from app.spec.from_playlist import playlist_spec
from app.schemas_gam import GamPlaylistDetail
from tests.fake_siblings import GAM, gam_playlist, playlist_item


def crisis():
    return gam_playlist("p1", "The financial crisis", [
        playlist_item("v1", start=62.0, end=101.5, label="On the bailout"),
        playlist_item("i1", "image", image_seconds=3.0),
        playlist_item("a1", "audio", start=10.0, end=25.0, label="Radio piece"),
        playlist_item("v1", start=300.0, end=320.0),
        playlist_item("v2"),
    ], description="Everyone on 2008.")


def test_the_playlists_are_listed_and_read_through_gvc(auth_client, siblings):
    siblings.playlists = {"p1": crisis()}
    listed = auth_client.get("/api/gam/playlists").json()
    assert listed["total"] == 1 and listed["data"][0]["name"] == "The financial crisis"
    assert listed["data"][0]["thumb_url"] == f"{GAM}/media/p1.jpg?exp=1&sig=x"

    detail = auth_client.get("/api/gam/playlists/p1").json()["data"]
    assert [i["asset_id"] for i in detail["items"]] == ["v1", "i1", "a1", "v1", "v2"]
    assert (detail["items"][0]["in_point"], detail["items"][0]["out_point"]) == (62.0, 101.5)
    assert auth_client.get("/api/gam/playlists/nope").status_code == 404


def test_a_gam_from_before_playlists_says_so(auth_client, siblings):
    siblings.playlists = None
    res = auth_client.get("/api/gam/playlists")
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "gam_without_playlists"


def test_a_project_is_laid_out_from_the_playlist(auth_client, siblings):
    siblings.playlists = {"p1": crisis()}
    res = auth_client.post("/api/projects/from-playlist", json={"playlist_id": "p1"})
    assert res.status_code == 201, res.text
    project = res.json()["data"]
    spec = project["spec"]
    assert project["origin"] == "playlist" and project["title"] == "The financial crisis"
    assert spec["source"]["kind"] == "playlist" and spec["source"]["playlist_id"] == "p1"

    title, bailout, image, radio, later, whole = spec["segments"]
    assert title["kind"] == "card" and title["card"]["subtitle"] == "Everyone on 2008."

    # A moment of video: its own sound, trimmed to the item's range.
    assert bailout["kind"] == "clip" and bailout["label"] == "On the bailout"
    assert bailout["chapter"] == "On the bailout"
    assert bailout["visual"]["audio"] == "play"
    assert bailout["visual"]["trim"] == {"in": 62.0, "out": 101.5}
    # The same video twice is one asset entry with two trims.
    assert later["visual"]["asset"] == bailout["visual"]["asset"]
    assert spec["assets"][bailout["visual"]["asset"]] == {
        "from": "gam", "id": "v1", "type": "video", "label": "Asset v1"}
    # A whole video has no trim.
    assert "trim" not in whole["visual"]

    assert image["kind"] == "scene" and image["duration"]["fixed"] == 3.0
    assert "narration" not in image

    # A sound: a scene on the background as long as the sound, which is anchored to it.
    assert radio["kind"] == "scene" and "visual" not in radio
    assert radio["duration"]["fixed"] == 15.0
    assert radio["overlays"][0]["title"] == "Radio piece"
    (track,) = spec["audio_tracks"]
    assert track["start"] == {"segment": radio["id"], "edge": "start", "offset": 0.0}
    assert track["end"] == {"segment": radio["id"], "edge": "end", "offset": 0.0}
    assert track["trim"] == {"in": 10.0, "out": 25.0}
    assert track["duck_under_narration"] is False


def test_the_renderer_times_each_segment_as_the_playlist_says(siblings):
    spec = playlist_spec(GamPlaylistDetail.model_validate(crisis()))
    keys = {ref.id: key for key, ref in spec.assets.items()}
    media = {
        keys["v1"]: Media(path="v1.mp4", kind="video", duration=1800.0, has_audio=True),
        keys["v2"]: Media(path="v2.mp4", kind="video", duration=40.0, has_audio=True),
        keys["i1"]: Media(path="i1.png", kind="image", width=1600, height=900),
        keys["a1"]: Media(path="a1.mp3", kind="audio", duration=60.0),
    }
    warnings = []
    units = plan_units(spec, media, warnings)
    seconds = [round(unit_duration(u, 0.0, 3.5), 3) for u in units]
    # Title card, the 39.5 s moment, the 3 s image, the 15 s sound, 20 s, the whole 40 s.
    assert seconds == [3.5, 39.5, 3.0, 15.0, 20.0, 40.0]
    assert warnings == []


def test_a_title_can_be_given_and_an_empty_or_missing_playlist_is_refused(auth_client, siblings):
    siblings.playlists = {"p1": crisis(), "p2": gam_playlist("p2", "Nothing", [])}
    named = auth_client.post("/api/projects/from-playlist",
                             json={"playlist_id": "p1", "title": "2008, in their words"})
    assert named.json()["data"]["spec"]["segments"][0]["card"]["title"] == "2008, in their words"

    empty = auth_client.post("/api/projects/from-playlist", json={"playlist_id": "p2"})
    assert empty.status_code == 400 and empty.json()["detail"]["code"] == "empty_playlist"
    missing = auth_client.post("/api/projects/from-playlist", json={"playlist_id": "zz"})
    assert missing.status_code == 404


def test_the_playlist_is_read_as_the_caller(client, siblings):
    import time

    from jose import jwt

    from app.config import settings

    token = jwt.encode({"sub": "notes-user-1", "username": "gecko", "exp": int(time.time()) + 3600},
                       settings.jwt_secret_key, algorithm="HS256")
    siblings.playlists = {"p1": crisis()}
    res = client.post("/api/projects/from-playlist", json={"playlist_id": "p1"},
                      headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 201, res.text
    asked = [r for r in siblings.requests if r.url.path == "/api/playlists/p1"]
    assert asked and asked[0].headers["authorization"] == f"Bearer {token}"
