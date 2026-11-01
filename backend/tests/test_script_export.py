"""Exporting a video's script as a Word document."""

import io

from docx import Document

from tests.fake_siblings import gam_asset, transcript


def _create(client, title="Salt Road"):
    res = client.post("/api/projects", json={"title": title})
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _spec(project, segments, assets=None):
    spec = project["spec"]
    spec["segments"] = segments
    spec["assets"] = assets or {}
    return spec


def _export(client, project_id, spec=None):
    res = client.post(f"/api/projects/{project_id}/script", json={"spec": spec})
    assert res.status_code == 200, res.text
    return res, Document(io.BytesIO(res.content))


def _text(doc):
    return [p.text for p in doc.paragraphs]


INTERVIEW = transcript(
    "parent",
    (100.0, 104.0, "We left before dawn.", 0),
    (104.0, 108.0, "The salt was heavy that year.", 1),
    (108.0, 112.0, "Nobody spoke of the road.", 0),
)


def test_narration_cards_overlays_and_clip_words_in_order(auth_client, siblings):
    siblings.assets["parent"] = gam_asset("parent", "Archive interview")
    siblings.transcripts["parent"] = INTERVIEW
    project = _create(auth_client)
    spec = _spec(project, [
        {"id": "t", "kind": "card", "card": {"variant": "title", "title": "Salt Road",
                                             "subtitle": "A caravan's year"}},
        {"id": "s1", "kind": "scene", "label": "The desert", "chapter": "Leaving",
         "narration": {"beats": [
             {"id": "b1", "text": "First, the desert. [pause:long] Then the wind."},
             {"id": "b2", "text": "Arrival", "kind": "heading"},
             {"id": "b3", "text": "Shown only", "speak": False},
         ]},
         "overlays": [{"id": "o1", "type": "lower_third", "title": "Agadez", "subtitle": "1971"}]},
        # Trimmed to the middle of the second line and the whole third: words, not
        # sentences, so the cut reads as it plays.
        {"id": "c1", "kind": "clip", "label": "The elder",
         "visual": {"asset": "iv", "trim": {"in": 106.0, "out": 112.0}, "audio": "play"}},
    ], {"iv": {"from": "gam", "id": "parent", "type": "video"}})

    res, doc = _export(auth_client, project["id"], spec)

    assert res.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert 'filename="Salt-Road-script.docx"' in res.headers["content-disposition"]
    text = _text(doc)
    assert text[0] == "Salt Road"
    order = [
        "1. Title card: Salt Road",
        "On screen: Salt Road / A caravan's year",
        "Leaving",
        "2. Scene: The desert",
        "On screen: Agadez / 1971",
        "First, the desert. [pause:long] Then the wind.",
        "Arrival",
        "On screen, not spoken: Shown only",
        "3. Clip: The elder",
        "From “Archive interview”, 1:46–1:52",
        "Speaker 2: heavy that year.",
        "Speaker 1: Nobody spoke of the road.",
    ]
    assert [t for t in text if t in order] == order
    # The heading beat is bold; the pause mark is kept.
    arrival = next(p for p in doc.paragraphs if p.text == "Arrival")
    assert arrival.runs[0].bold
    # Counts only words spoken aloud: 7 of narration (the pause mark and the silent
    # beat don't count), 8 said in the clip.
    assert "7 words of narration" in text[1] and "8 words said in clips" in text[1]


def test_a_gam_clip_reads_its_parents_transcript_within_its_points(auth_client, siblings):
    """A GAM clip has no transcript of its own: it's the parent's between in and out,
    and the spec's trim is relative to the clip."""
    siblings.assets["parent"] = gam_asset("parent", "Archive interview")
    siblings.assets["clip"] = gam_asset("clip", "The elder, cut", parent_asset_id="parent",
                                        in_point=104.0, out_point=110.0)
    siblings.transcripts["parent"] = INTERVIEW
    project = _create(auth_client)
    spec = _spec(project, [
        {"id": "c1", "kind": "clip", "visual": {"asset": "k", "audio": "play"}},
    ], {"k": {"from": "gam", "id": "clip"}})

    _, doc = _export(auth_client, project["id"], spec)

    text = _text(doc)
    assert "1. Clip: The elder, cut" in text
    assert "From “The elder, cut”, 1:44–1:50" in text
    # The first line ends at 104 s and the third runs past 110 s, so only their words
    # inside the clip's points are in.
    assert "Speaker 2: The salt was heavy that year." in text
    assert "Speaker 1: Nobody spoke of" in text
    assert not any("dawn" in t or "road" in t for t in text)
    paths = [r.url.path for r in siblings.gam_requests()]
    assert "/api/assets/parent/transcript" in paths
    assert "/api/assets/clip/transcript" not in paths


def test_a_scenes_footage_is_muted_so_its_words_are_not_in_the_script(auth_client, siblings):
    siblings.assets["parent"] = gam_asset("parent", "Archive interview")
    siblings.transcripts["parent"] = INTERVIEW
    project = _create(auth_client)
    spec = _spec(project, [
        {"id": "s1", "kind": "scene", "visual": {"asset": "iv"},
         "narration": {"beats": [{"id": "b1", "text": "Over the footage."}]}},
    ], {"iv": {"from": "gam", "id": "parent"}})

    _, doc = _export(auth_client, project["id"], spec)

    assert not any("salt" in t for t in _text(doc))
    assert not any(r.url.path.endswith("/transcript") for r in siblings.gam_requests())


def test_a_clip_that_cant_be_read_is_explained_and_the_rest_still_exports(auth_client, siblings):
    siblings.gam_down = True
    project = _create(auth_client)
    spec = _spec(project, [
        {"id": "c0", "kind": "clip", "visual": {"asset": "find"}},
        {"id": "c1", "kind": "clip", "visual": {"asset": "a"}},
        {"id": "c2", "kind": "clip", "visual": {"asset": "b"}},
        {"id": "s1", "kind": "scene", "narration": {"beats": [{"id": "b1", "text": "Still here."}]}},
    ], {"find": {"from": "search", "query": "the salt road"},
        "a": {"from": "gam", "id": "x1"}, "b": {"from": "gam", "id": "x2"}})

    _, doc = _export(auth_client, project["id"], spec)

    text = _text(doc)
    assert "Footage still to find: “the salt road”." in text
    assert sum(t.startswith("The asset library couldn't be read") for t in text) == 2
    assert "Still here." in text
    # Unreachable once, then not asked again.
    assert len([r for r in siblings.requests if r.url.host == "gam.test"]) == 1


def test_without_a_draft_the_saved_spec_is_exported(auth_client, siblings):
    project = _create(auth_client, title="Saved one")
    _, doc = _export(auth_client, project["id"])
    assert _text(doc)[0] == "Saved one"


def test_an_invalid_draft_is_refused_and_another_users_project_is_not_found(
        auth_client, siblings, switch_user):
    project = _create(auth_client)
    bad = auth_client.post(f"/api/projects/{project['id']}/script",
                           json={"spec": {"segments": [{"id": "x", "kind": "nope"}]}})
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_spec"

    switch_user("someone-else")
    gone = auth_client.post(f"/api/projects/{project['id']}/script", json={})
    assert gone.status_code == 404
