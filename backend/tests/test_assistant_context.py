"""What the assistant is told about the video's asset registry."""

from app.assistant.prompt import context


def _registry(data):
    text = context(data, focus=None, from_scratch=False)
    return text.split("Asset registry:\n", 1)[1]


def test_a_filled_placeholder_reads_as_done_and_an_orphan_as_unused():
    data = {
        "title": "T",
        "assets": {
            "a_old": {"from": "generate", "type": "image", "prompt": "A dam"},
            "a_dam": {"from": "generate", "type": "image", "prompt": "A dam",
                      "status": "ready", "result": {"from": "gam", "id": "g1"}},
            "a_river": {"from": "search", "query": "river", "status": "resolved",
                        "result": {"from": "gam", "id": "g2"}},
            "a_todo": {"from": "generate", "type": "image", "prompt": "A bridge"},
        },
        "segments": [
            {"id": "s1", "kind": "scene", "visual": {"asset": "a_dam"}},
            {"id": "s2", "kind": "scene", "visual": {"asset": "a_river"}},
            {"id": "s3", "kind": "scene", "visual": {"asset": "a_todo"}},
        ],
    }
    lines = {line.split(":", 1)[0]: line for line in _registry(data).splitlines()
             if line.startswith("- ")}
    assert "generated image, done" in lines["- a_dam"]
    assert "gam_id g1" in lines["- a_dam"]
    assert "found footage" in lines["- a_river"]
    assert "to generate" in lines["- a_todo"]
    assert "not used" not in lines["- a_todo"]
    assert "to generate" in lines["- a_old"]
    assert "[not used in the video]" in lines["- a_old"]
