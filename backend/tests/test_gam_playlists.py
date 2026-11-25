"""GAM's playlists searched, read and changed through GVC, as the signed-in user.

A playlist is GAM's: these check that each change reaches GAM as the caller, that GAM's
own refusals come back as the person's to fix, and that searching works against a GAM
from before its playlist search too.
"""

from tests.fake_siblings import GAM, gam_asset, gam_playlist, playlist_item

TOKEN = {"Authorization": "Bearer user-token"}


def library(siblings):
    siblings.assets.update({
        "v1": gam_asset("v1", "Interview"),
        "i1": gam_asset("i1", "Map", "image"),
        "d1": gam_asset("d1", "Report", "document"),
    })
    siblings.playlists = {
        "p1": gam_playlist("p1", "The financial crisis", [
            playlist_item("v1", start=62.0, end=101.5, label="On the bailout"),
            playlist_item("i1", "image", image_seconds=3.0),
        ], description="Everyone on 2008."),
        "p2": gam_playlist("p2", "River", [], description="Floods"),
    }


def test_playlists_are_searched_by_name_and_description(auth_client, siblings):
    library(siblings)
    names = lambda q: [p["name"] for p in auth_client.get(  # noqa: E731
        "/api/gam/playlists", params={"q": q}).json()["data"]]
    assert names("crisis") == ["The financial crisis"]
    assert names("FLOOD") == ["River"]
    assert sorted(names("")) == ["River", "The financial crisis"]
    assert siblings.gam_requests()[0].url.params["q"] == "crisis"


def test_a_gam_from_before_playlist_search_is_searched_here(auth_client, siblings):
    library(siblings)
    siblings.playlists_search = False
    found = auth_client.get("/api/gam/playlists", params={"q": "2008"}).json()
    assert [p["name"] for p in found["data"]] == ["The financial crisis"] and found["total"] == 1


def test_a_playlists_items_come_in_order_with_what_previews_them(auth_client, siblings):
    library(siblings)
    items = auth_client.get("/api/gam/playlists/p1").json()["data"]["items"]
    assert [(i["asset_id"], i["start"], i["end"]) for i in items] == [
        ("v1", 62.0, 101.5), ("i1", 0.0, 3.0)]
    assert items[0]["file_url"] == f"{GAM}/media/v1.bin?exp=1&sig=x"


def test_a_playlist_is_made_with_its_first_items_as_the_caller(auth_client, siblings):
    library(siblings)
    res = auth_client.post("/api/gam/playlists", json={
        "name": "  Picks ", "description": "For the edit",
        "items": [{"asset_id": "v1", "in_point": 5, "out_point": 9, "label": "Opening"}]},
        headers=TOKEN)
    assert res.status_code == 201, res.text
    made = res.json()["data"]
    assert made["name"] == "Picks" and made["item_count"] == 1
    assert (made["items"][0]["start"], made["items"][0]["end"]) == (5.0, 9.0)
    kind, body, auth = siblings.playlist_writes[-1]
    # The person's own token, so GAM checks the assets are theirs.
    assert kind == "create" and auth == "Bearer user-token"
    # Unset fields are not sent, so GAM applies its own defaults.
    assert body["items"] == [{"asset_id": "v1", "in_point": 5.0, "out_point": 9.0,
                              "label": "Opening"}]


def test_items_are_added_at_a_position_and_removed(auth_client, siblings):
    library(siblings)
    added = auth_client.post("/api/gam/playlists/p1/items", json={
        "items": [{"asset_id": "v1"}], "position": 1})
    assert added.status_code == 201, added.text
    items = added.json()["data"]["items"]
    assert [i["asset_id"] for i in items] == ["v1", "v1", "i1"]
    assert added.json()["data"]["item_count"] == 3

    removed = auth_client.delete(f"/api/gam/playlists/p1/items/{items[0]['id']}")
    assert removed.status_code == 200
    assert [i["asset_id"] for i in removed.json()["data"]["items"]] == ["v1", "i1"]
    # The asset stays in the library: only the item went.
    assert "v1" in siblings.assets


def test_what_gam_refuses_is_the_persons_to_fix(auth_client, siblings):
    library(siblings)
    res = auth_client.post("/api/gam/playlists/p1/items", json={"items": [{"asset_id": "d1"}]})
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "not_playable"
    res = auth_client.post("/api/gam/playlists", json={"name": "X", "items": [{"asset_id": "nope"}]})
    assert res.status_code == 400 and res.json()["detail"]["message"] == "No such asset."
    assert auth_client.post("/api/gam/playlists", json={"name": ""}).status_code == 422
    assert auth_client.post("/api/gam/playlists/p1/items", json={"items": []}).status_code == 422


def test_a_missing_playlist_or_item_is_404(auth_client, siblings):
    library(siblings)
    res = auth_client.post("/api/gam/playlists/nope/items", json={"items": [{"asset_id": "v1"}]})
    assert res.status_code == 404 and res.json()["detail"]["code"] == "not_found"
    assert auth_client.delete("/api/gam/playlists/p1/items/nope").status_code == 404


def test_a_gam_from_before_playlists_says_so_on_a_change(auth_client, siblings):
    siblings.playlists = None
    res = auth_client.post("/api/gam/playlists", json={"name": "Picks"})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "gam_without_playlists"
