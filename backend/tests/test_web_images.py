"""Pictures from the web: found through the suite, chosen by a person, filed in GAM.

The suite and GAM are both faked (`test_suite_backend.FakeSuite`, `fake_siblings`). What
is checked is what GVC asks each of them, and that nothing from the web reaches a video
except as a shortlist on a placeholder.
"""

import httpx
import pytest

from app.assistant import tools as T
from app.config import settings
from app.spec.model import MAX_WEB_CANDIDATES
from app.spec.validation import parse_spec
from tests.test_assistant_tools import spec
from tests.test_suite_backend import HEADERS, fake_suite, reply, run  # noqa: F401
from tests.test_assistant_turns import engine_for_worker, library  # noqa: F401

HITS = [
    {"image_url": "https://img.test/river.jpg", "page_url": "https://example.test/river",
     "title": "Dry riverbed", "width": 1920, "height": 1080, "description": "A cracked riverbed"},
    {"image_url": "https://img.test/dam.jpg", "description": "A concrete dam"},
]


def working(hits=HITS, **extra):
    asked = []
    w = T.Working(spec(), image_search=lambda q: asked.append(q) or [dict(h) for h in hits], **extra)
    return w, asked


# ─── the assistant's tool ────────────────────────────────────────────────────


def test_find_images_leaves_a_shortlist_on_the_scene_not_a_picture():
    w, asked = working()
    out = T.find_images(w, "a dry riverbed", segment_id="s_valley")

    assert asked == ["a dry riverbed"]
    key = w.data["segments"][1]["visual"]["asset"]
    ref = w.data["assets"][key]
    assert ref["from"] == "search" and ref["type"] == "image" and ref.get("status", "unresolved") == "unresolved"
    assert [c["image_url"] for c in ref["candidates"]] == ["https://img.test/river.jpg", "https://img.test/dam.jpg"]
    # The model reads what it found, numbered, and is told the person chooses.
    assert "[1] 1920x1080 A cracked riverbed (https://example.test/river)" in out
    assert "[2] A concrete dam" in out and "choose" in out
    assert parse_spec(w.data)[1] == []


@pytest.mark.parametrize("use_as", ["overlay", "background", "none"])
def test_find_images_can_be_for_an_overlay_the_background_or_later(use_as):
    w, _ = working()
    T.find_images(w, "a map of the river", segment_id="s_valley" if use_as == "overlay" else None,
                  use_as=use_as, label="River map")
    key = "a_river_map"
    assert w.data["assets"][key]["label"] == "River map"
    if use_as == "overlay":
        assert w.data["segments"][1]["overlays"][-1]["asset"] == key
    elif use_as == "background":
        assert w.data["style"]["background"] == {"type": "image", "asset": key}
    else:
        assert w.data["segments"][1]["visual"]["asset"] == "a_map"
    assert parse_spec(w.data)[1] == []


def test_what_a_site_sends_is_cut_to_what_the_spec_holds():
    long = "x" * 1000
    w, _ = working(hits=[
        {"image_url": "https://img.test/a.jpg", "title": long, "description": long,
         "page_url": "javascript:alert(1)", "width": "big", "extra": "dropped"},
        {"image_url": "ftp://img.test/b.jpg"},
        {"image_url": "https://img.test/a.jpg"},
    ] + [{"image_url": f"https://img.test/{i}.jpg"} for i in range(20)])
    T.find_images(w, "anything", use_as="none")
    (ref,) = [r for r in w.data["assets"].values() if r["from"] == "search"]
    first = ref["candidates"][0]
    assert set(first) == {"image_url", "title", "description"}
    assert (len(first["title"]), len(first["description"])) == (300, 500)
    assert len(ref["candidates"]) == MAX_WEB_CANDIDATES
    assert parse_spec(w.data)[1] == []


def test_nothing_found_changes_nothing():
    w, _ = working(hits=[])
    before = w.data
    assert "No pictures found" in T.find_images(w, "zzz", segment_id="s_valley")
    assert w.data == before and w.changes == []


def test_picture_searches_are_capped_and_a_bad_segment_costs_none():
    w, asked = working(max_image_searches=1)
    with pytest.raises(T.ToolFailed, match="No segment|segment"):
        T.find_images(w, "x", segment_id="s_nope")
    assert asked == []
    T.find_images(w, "one", use_as="none")
    with pytest.raises(T.ToolFailed, match="1 picture searches"):
        T.find_images(w, "two", use_as="none")


def test_the_tool_is_offered_only_where_there_is_a_web():
    assert "find_images" not in [s.name for s in T.specs_for(T.Working({}))]
    assert "find_images" in [s.name for s in T.specs_for(working()[0])]


def test_too_many_candidates_is_an_invalid_spec():
    data = spec()
    data["assets"]["a_web"] = {"from": "search", "query": "x", "type": "image",
                               "candidates": [{"image_url": f"https://i.test/{i}.jpg"}
                                              for i in range(MAX_WEB_CANDIDATES + 1)]}
    assert parse_spec(data)[1]


def test_a_turn_on_the_suite_finds_pictures_credited_to_gvc(auth_client, fake_suite, library, engine_for_worker):
    fake_suite.script += [
        reply("", ("find_images", {"query": "dry riverbed", "use_as": "background"})),
        reply("I found some riverbed pictures; choose one for the background."),
    ]
    done = run(auth_client, prompt="Make a short video about drought")

    assert done["status"] == "done", done
    assert "find_images" in [t["name"] for t in fake_suite.chats[0]["tools"]]
    (asked,) = fake_suite.image_searches
    assert (asked["query"], asked["app"]) == ("dry riverbed", "gvc")
    proposed = done["proposed_spec"]
    key = proposed["style"]["background"]["asset"]
    assert len(proposed["assets"][key]["candidates"]) == 2


# ─── the editor's Web tab ────────────────────────────────────────────────────


def test_the_web_tab_searches_through_the_suite(auth_client, fake_suite):
    res = auth_client.get("/api/web/images", params={"q": "dry riverbed", "project_id": "p1"}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2 and body["data"][0]["page_url"] == "https://example.test/river"
    assert fake_suite.image_searches[0]["subject_ref"] == "gvc:project:p1"


def test_the_suites_sentence_is_passed_on(auth_client, fake_suite):
    fake_suite.image_status = httpx.Response(409, json={"detail": {
        "code": "images_unsupported", "message": "Set up Tavily, Brave or SearXNG in Gecko Suite."}})
    res = auth_client.get("/api/web/images", params={"q": "x"}, headers=HEADERS)
    assert res.status_code == 409
    assert res.json()["detail"] == {"code": "images_unsupported",
                                    "message": "Set up Tavily, Brave or SearXNG in Gecko Suite."}


def test_without_the_suite_the_web_tab_says_why(auth_client, monkeypatch):
    monkeypatch.setattr(settings, "ai_backend", "local")
    res = auth_client.get("/api/web/images", params={"q": "x"}, headers=HEADERS)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "web_search_unavailable"


def test_a_suite_that_is_down_is_a_503(auth_client, fake_suite):
    fake_suite.down = True
    res = auth_client.get("/api/web/images", params={"q": "x"}, headers=HEADERS)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "suite_unavailable"


def test_an_empty_query_asks_nothing(auth_client, fake_suite):
    assert auth_client.get("/api/web/images", params={"q": " "}, headers=HEADERS).json()["total"] == 0
    assert fake_suite.image_searches == []


def test_a_chosen_picture_is_filed_in_gam_as_the_caller(auth_client, siblings):
    body = {"image_url": "https://img.test/river.jpg", "page_url": "https://example.test/river",
            "title": "Dry riverbed", "description": "A cracked riverbed"}
    res = auth_client.post("/api/gam/import-image", json=body, headers=HEADERS)
    assert res.status_code == 200, res.text
    asset = res.json()["data"]
    assert asset["id"] == "gam-web-1" and asset["asset_type"] == "image"
    (sent,) = siblings.imported_images
    assert sent["page_url"] == "https://example.test/river" and sent["title"] == "Dry riverbed"
    assert sent["authorization"] == HEADERS["Authorization"]


def test_gams_refusal_is_its_own_sentence(auth_client, siblings):
    siblings.import_image_status = 400
    res = auth_client.post("/api/gam/import-image", json={"image_url": "https://img.test/x"}, headers=HEADERS)
    assert res.status_code == 400
    assert res.json()["detail"]["message"] == "That link is not a picture GAM can store"


def test_a_gam_without_the_route_says_it_needs_updating(auth_client, siblings):
    siblings.import_image_status = 404
    res = auth_client.post("/api/gam/import-image", json={"image_url": "https://img.test/x"}, headers=HEADERS)
    assert res.json()["detail"]["code"] == "gam_without_image_import"
