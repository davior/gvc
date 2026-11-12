"""The assistant running on Gecko Suite (`AI_BACKEND=suite`), with the suite faked.

The same turn as test_assistant_turns, but every model call goes over HTTP to a fake of
the suite's gateway. So these check what GVC sends (the job it names, the history it
replays, the project it attributes spend to), what it does with the answers, and what it
does when the suite says no or is not there: the app must keep working.
"""

import json
from typing import Any, Callable, Dict, List, Optional

import httpx
import pytest

from app import suite
from app.assistant import worker
from app.config import settings
from app.models.usage import UsageEvent
from tests.conftest import TEST_USER_ID
from tests.fake_siblings import gam_asset, hit
from tests.test_assistant_turns import DRAFT, engine_for_worker, library, start  # noqa: F401

TOKEN = "notes-session-jwt"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def model(label="Claude Opus 5.5", model_id="claude-opus-5-5", capabilities=None) -> dict:
    return {"id": "m1", "label": label, "model_id": model_id, "vendor": "anthropic",
            "capabilities": capabilities or ["chat", "tools", "vision"]}


def reply(text="", *calls, stop=None, tokens=(1000, 200), cost=0.01, served="claude-opus-5-5") -> dict:
    """What the suite's POST /ai/chat answers, as `ChatResult`."""
    tool_calls = [{"id": f"c{i}", "name": name, "arguments": args, "parse_error": None}
                  for i, (name, args) in enumerate(calls)]
    return {
        "text": text, "tool_calls": tool_calls, "stop": stop or ("tool_use" if calls else "end"),
        "refusal_category": None,
        "message": {"role": "assistant", "text": text, "tool_calls": tool_calls,
                    "raw": {"protocol": "anthropic", "message": {"role": "assistant", "content": [
                        {"type": "thinking", "thinking": "", "signature": "sig"}]}}},
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1],
                  "cache_read_tokens": 0, "cache_write_tokens": 0},
        "model": served, "model_ref": "m1", "provider": "Claude", "vendor": "anthropic",
        "task": None, "cost": cost, "currency": "USD", "cost_estimated": True,
        "usage_event_id": "u",
    }


class FakeSuite:
    def __init__(self):
        self.script: List[dict] = []
        self.chats: List[dict] = []
        self.resolved: List[str] = []
        # task -> model (or None for "nothing routed"). Unlisted tasks resolve to the default.
        self.routing: Dict[str, Optional[dict]] = {}
        self.default: Optional[dict] = model()
        self.down = False
        self.chat_status: Optional[httpx.Response] = None
        self.searches: List[dict] = []
        self.search_down = False
        self.persona_queries: List[dict] = []
        self.personas: List[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused")
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.url.path == "/api/v1/resolve":
            task = request.url.params["task"]
            self.resolved.append(task)
            chosen = self.routing.get(task, self.default)
            return httpx.Response(200, json={"data": {"task": task, "app": "gvc", "model": chosen}})
        if request.url.path == "/api/v1/search/web":
            self.searches.append(json.loads(request.content))
            if self.search_down:
                return httpx.Response(502, json={"detail": {"code": "upstream_error",
                                                            "message": "search is down"}})
            return httpx.Response(200, json={"data": {"results": [
                {"title": "Water wars, a history", "url": "https://example.test/ww",
                 "snippet": "Disputes over rivers since antiquity."}]}})
        if request.url.path == "/api/v1/personas":
            self.persona_queries.append(dict(request.url.params))
            return httpx.Response(200, json={"data": self.personas, "total": len(self.personas),
                                             "limit": 0, "offset": 0})
        if request.url.path == "/api/v1/ai/chat":
            body = json.loads(request.content)
            self.chats.append(body)
            if self.chat_status is not None:
                return self.chat_status
            assert self.script, "the suite was asked more often than the script allows"
            result = self.script.pop(0)
            if body.get("stream"):
                # The gateway's frames: text as deltas, a keepalive comment for the
                # silent stretches (a tool call being written), then the whole result.
                frames = [": keepalive\n\n"]
                for piece in (result["text"][:5], result["text"][5:]):
                    if piece:
                        frames.append(f"event: delta\ndata: {json.dumps({'text': piece})}\n\n")
                frames.append(f"event: final\ndata: {json.dumps(result)}\n\n")
                return httpx.Response(200, content="".join(frames).encode(),
                                      headers={"content-type": "text/event-stream"})
            return httpx.Response(200, json={"data": result})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")


@pytest.fixture
def fake_suite(monkeypatch):
    fake = FakeSuite()
    monkeypatch.setattr(settings, "ai_backend", "suite")
    monkeypatch.setattr(suite, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


def run(client, **body):
    res = client.post("/api/assistant/turns", json={"prompt": "Make it", **body}, headers=HEADERS)
    assert res.status_code == 202, res.text
    turn = res.json()["data"]
    worker._run(turn["id"])
    return client.get(f"/api/assistant/turns/{turn['id']}").json()["data"]


def test_a_draft_turn_runs_on_the_suite_and_becomes_a_project(
        auth_client, session, fake_suite, library, engine_for_worker):
    fake_suite.script += [
        reply("Looking.", ("search_assets", {"query": "water", "type": "video"})),
        reply("", ("replace_spec", {"spec": DRAFT})),
        reply("", ("update_segment", {"segment_id": "s_valley",
                                      "changes": {"transition_in": {"style": "dissolve"}}})),
        reply("", ("set_visual", {"segment_id": "s_valley", "gam_id": "r"})),
        reply("A two-scene draft."),
    ]
    done = run(auth_client, prompt="A short video about the water wars")

    assert done["status"] == "done", done
    assert done["reply"] == "A two-scene draft." and done["outcome"] == "pending"
    assert done["proposed_spec"]["segments"][1]["transition_in"] == {"style": "dissolve"}

    # A new video is a draft, which the suite can route to a different model than an edit.
    first = fake_suite.chats[0]
    assert first["task"] == "chat.draft" and first["app"] == "gvc"
    assert "set_visual" in [t["name"] for t in first["tools"]]
    assert "new video" in first["system"][-1]
    # Each later round replays what the suite returned, the vendor's own message included
    # (thinking blocks must survive), and answers every tool call.
    second = fake_suite.chats[1]
    assert second["messages"][1]["raw"]["message"]["content"][0]["type"] == "thinking"
    assert second["messages"][2]["role"] == "tool"

    # The suite counted the spend; this app keeps only the turn's running total.
    assert session.query(UsageEvent).count() == 0
    assert done["cost"] == pytest.approx(0.05)


def test_a_turn_streams_so_a_long_reply_is_not_timed_out_and_shows_its_progress(
        auth_client, fake_suite, library, engine_for_worker, monkeypatch):
    monkeypatch.setattr(worker, "STREAM_WRITE_SECONDS", 0)
    details = []
    real_write = worker.set_fields

    def watching(session, row, **fields):
        if "detail" in fields:
            details.append(fields["detail"])
        return real_write(session, row, **fields)

    monkeypatch.setattr(worker, "set_fields", watching)
    fake_suite.script += [
        reply("Looking.", ("search_assets", {"query": "water", "type": "video"})),
        reply("", ("replace_spec", {"spec": DRAFT})),
        reply("", ("update_segment", {"segment_id": "s_valley",
                                      "changes": {"transition_in": {"style": "dissolve"}}})),
        reply("", ("set_visual", {"segment_id": "s_valley", "gam_id": "r"})),
        reply("A two-scene draft."),
    ]
    done = run(auth_client, prompt="A short video about the water wars")

    assert done["status"] == "done", done
    assert done["reply"] == "A two-scene draft."
    assert all(chat["stream"] is True for chat in fake_suite.chats)
    # Counted across the turn: "Looking." then "A two-scene draft."
    assert details[:2] == ["writing (5 characters)", "writing (8 characters)"]
    assert "writing (26 characters)" in details


def test_an_edit_names_the_edit_job_and_the_project_it_is_about(
        auth_client, fake_suite, library, engine_for_worker):
    from tests.test_assistant_turns import VALID, project_with

    project = project_with(auth_client, VALID)
    fake_suite.script += [reply("Nothing to change.")]
    done = run(auth_client, project_id=project["id"], prompt="check it",
               draft_spec=project["spec"], base_version=project["version"])
    assert done["status"] == "done"
    sent = fake_suite.chats[0]
    assert sent["task"] == "chat.edit"
    # What the spend was for, so the suite can answer "what did this video cost".
    assert sent["subject_ref"] == f"gvc:project:{project['id']}"


def test_a_picture_is_refused_before_the_turn_when_the_model_cannot_see(
        auth_client, fake_suite, engine_for_worker):
    fake_suite.default = model("DeepSeek Chat", "deepseek-chat", ["chat", "tools"])
    png = (b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    res = auth_client.post("/api/assistant/sessions", json={})
    session_id = res.json()["data"]["id"]
    res = auth_client.post(f"/api/assistant/sessions/{session_id}/attachments/file",
                           files={"file": ("p.png", png, "image/png")}, headers=HEADERS)
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "images_unsupported"
    assert "DeepSeek Chat" in res.json()["detail"]["message"]


def test_no_model_routed_is_a_409_that_says_where_to_set_one(auth_client, fake_suite):
    fake_suite.default = None
    res = auth_client.post("/api/assistant/turns", json={"prompt": "Make it"}, headers=HEADERS)
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_provider"
    assert "Gecko Suite" in res.json()["detail"]["message"]


def test_a_suite_that_is_down_is_a_503_and_the_rest_of_the_app_still_works(
        auth_client, fake_suite):
    fake_suite.down = True
    res = auth_client.post("/api/assistant/turns", json={"prompt": "Make it"}, headers=HEADERS)
    assert res.status_code == 503 and res.json()["detail"]["code"] == "ai_unavailable"
    assert "Everything else" in res.json()["detail"]["message"]
    # A video can be made entirely by hand.
    assert auth_client.get("/api/projects").status_code == 200
    made = auth_client.post("/api/projects", json={"spec": {"spec_version": "0.1", "title": "By hand"}})
    assert made.status_code == 201


def test_the_suite_going_away_mid_turn_ends_that_turn_with_a_sentence(
        auth_client, fake_suite, library, engine_for_worker):
    started = auth_client.post("/api/assistant/turns", json={"prompt": "Make it"}, headers=HEADERS)
    assert started.status_code == 202
    turn_id = started.json()["data"]["id"]
    fake_suite.down = True
    worker._run(turn_id)
    done = auth_client.get(f"/api/assistant/turns/{turn_id}").json()["data"]
    assert done["status"] == "error"
    assert "can't be reached" in done["error"]


def test_a_refusal_by_the_suite_is_shown_as_its_own_sentence(
        auth_client, fake_suite, library, engine_for_worker):
    fake_suite.chat_status = httpx.Response(409, json={"detail": {
        "code": "provider_key_missing", "message": "Claude has no usable API key. Set it in Gecko Suite."}})
    started = auth_client.post("/api/assistant/turns", json={"prompt": "Make it"}, headers=HEADERS)
    worker._run(started.json()["data"]["id"])
    done = auth_client.get(f"/api/assistant/turns/{started.json()['data']['id']}").json()["data"]
    assert done["status"] == "error" and "Set it in Gecko Suite" in done["error"]


def test_a_session_without_a_token_cannot_use_the_suite_and_says_so(auth_client, fake_suite):
    res = auth_client.post("/api/assistant/turns", json={"prompt": "Make it"})  # no Authorization
    assert res.status_code == 409 and res.json()["detail"]["code"] == "no_session"


def test_a_clip_picking_pass_is_its_own_cheaper_job(
        auth_client, fake_suite, library, engine_for_worker):
    """find_clips reads a whole transcript, so it names chat.quick and can be given a cheap
    model, falling back to the assistant's when the suite has no such routing."""
    fake_suite.routing["chat.quick"] = model("Claude Haiku 5.5", "claude-haiku-5-5")
    from tests.test_assistant_tools import river_transcript

    river_transcript(library)
    fake_suite.script += [
        reply("", ("search_assets", {"query": "water", "type": "video"})),
        reply("", ("find_clips", {"gam_id": "r", "idea": "the water is gone"})),
        reply('[{"first": 0, "last": 0, "score": 7}]'),  # the picker's answer
        reply("Found it."),
    ]
    done = run(auth_client, prompt="find the moment")
    assert done["status"] == "done", done
    assert [c["task"] for c in fake_suite.chats] == [
        "chat.draft", "chat.draft", "chat.quick", "chat.draft"]
    picker = fake_suite.chats[2]
    assert picker["tools"] == []  # a fresh conversation with no tools
    assert picker["messages"][0]["role"] == "user"


def test_local_is_still_the_default_and_unknown_values_are_refused():
    from pydantic import ValidationError

    from app.config import Settings

    assert settings.ai_backend in ("local", "suite")
    with pytest.raises(ValidationError):
        Settings(jwt_secret_key="a-strong-enough-test-secret", ai_backend="cloud")
    assert Settings(jwt_secret_key="a-strong-enough-test-secret").ai_backend == "local"


# ─── the web ─────────────────────────────────────────────────────────────────


def test_the_assistant_can_search_the_web_and_gets_the_results_to_cite(
        auth_client, fake_suite, library, engine_for_worker):
    fake_suite.script += [
        reply("", ("web_search", {"query": "history of water wars"})),
        reply("Rivers have been fought over since antiquity (per the web)."),
    ]
    done = run(auth_client, prompt="Write a line about water wars")

    assert done["status"] == "done", done
    # Offered, and the model told when to use it.
    first = fake_suite.chats[0]
    assert "web_search" in [t["name"] for t in first["tools"]]
    assert any("web_search" in block for block in first["system"])
    # Asked of the suite as the signed-in user, credited to GVC.
    (search,) = fake_suite.searches
    assert search["query"] == "history of water wars" and search["app"] == "gvc"
    # Numbered, so the model can cite it.
    result = [r for m in fake_suite.chats[1]["messages"] if m["role"] == "tool"
              for r in m["results"]][0]
    assert result["is_error"] is False and "[1] Water wars, a history" in result["content"]
    assert any(s["kind"] == "search" and "web" in s["text"] for s in done["steps"])
    # Reading the web changes nothing in the video.
    assert done["proposed_spec"] is None


def test_a_search_on_a_project_is_credited_to_it(auth_client, fake_suite, library, engine_for_worker):
    from tests.test_assistant_turns import VALID, project_with

    project = project_with(auth_client, VALID)
    fake_suite.script += [reply("", ("web_search", {"query": "x"})), reply("Nothing to change.")]
    run(auth_client, project_id=project["id"], prompt="check a fact",
        draft_spec=project["spec"], base_version=project["version"])
    assert fake_suite.searches[0]["subject_ref"] == f"gvc:project:{project['id']}"


def test_a_failed_search_is_for_the_model_to_read_not_a_failed_turn(
        auth_client, fake_suite, library, engine_for_worker):
    fake_suite.search_down = True
    fake_suite.script += [reply("", ("web_search", {"query": "x"})), reply("I couldn't look that up.")]
    done = run(auth_client, prompt="Look something up")
    assert done["status"] == "done" and "couldn't look" in done["reply"]
    result = [r for m in fake_suite.chats[1]["messages"] if m["role"] == "tool"
              for r in m["results"]][0]
    assert result["is_error"] is True and "search failed" in result["content"]


def test_the_web_tool_is_not_offered_where_there_is_no_web():
    from app.assistant import tools as T

    assert "web_search" not in [s.name for s in T.specs_for(T.Working({}))]
    searching = T.Working({}, web_search=lambda query: [])
    assert "web_search" in [s.name for s in T.specs_for(searching)]


def test_searches_are_capped_so_a_model_cannot_loop_on_them():
    from app.assistant import tools as T

    seen = []
    working = T.Working({}, web_search=lambda query: seen.append(query) or [], max_web_searches=2)
    T.web_search(working, "one")
    T.web_search(working, "two")
    with pytest.raises(T.ToolFailed, match="2 web searches"):
        T.web_search(working, "three")
    assert seen == ["one", "two"]
    with pytest.raises(T.ToolFailed, match="query"):
        T.web_search(T.Working({}, web_search=lambda q: []), "   ")


# ─── personas ────────────────────────────────────────────────────────────────

PERSONAS = [
    {"id": "p-doc", "name": "Documentarian", "description": "Plain and sober.", "avatar": None,
     "system_prompt": "SECRET PROMPT", "scope": "instance", "app": None, "model_overrides": {},
     "sort_order": 0, "writable": False},
    {"id": "p-gvc", "name": "Trailer voice", "description": "", "avatar": None,
     "system_prompt": "x", "scope": "user", "app": "gvc", "model_overrides": {}, "sort_order": 1,
     "writable": True},
]


def test_the_picker_lists_the_suites_personas_without_their_prompts(auth_client, fake_suite):
    fake_suite.personas = PERSONAS
    res = auth_client.get("/api/assistant/personas", headers=HEADERS)
    assert res.status_code == 200
    assert [p["name"] for p in res.json()["data"]] == ["Documentarian", "Trailer voice"]
    assert "SECRET PROMPT" not in res.text and "system_prompt" not in res.text
    assert fake_suite.persona_queries == [{"app": "gvc"}]


def test_no_personas_when_there_are_none_or_the_suite_is_down_or_not_in_use(
        auth_client, fake_suite, monkeypatch):
    assert auth_client.get("/api/assistant/personas", headers=HEADERS).json()["data"] == []
    fake_suite.personas = PERSONAS
    fake_suite.down = True
    assert auth_client.get("/api/assistant/personas", headers=HEADERS).json()["data"] == []
    fake_suite.down = False
    # No session to ask the suite as: a picker is not worth an error.
    assert auth_client.get("/api/assistant/personas").json()["data"] == []
    monkeypatch.setattr(settings, "ai_backend", "local")
    assert auth_client.get("/api/assistant/personas", headers=HEADERS).json()["data"] == []


def test_a_turn_asked_as_a_persona_is_sent_to_the_suite_as_that_persona(
        auth_client, fake_suite, library, engine_for_worker):
    fake_suite.script += [reply("As the documentarian."), reply("As nobody in particular.")]
    first = run(auth_client, prompt="Open the film", persona_id="p-doc")
    assert first["persona_id"] == "p-doc" and fake_suite.chats[0]["persona_id"] == "p-doc"
    second = run(auth_client, prompt="Open another", session_id=first["session_id"])
    # A persona belongs to the turn: the next one is asked as whatever the picker then says.
    assert second["persona_id"] is None and "persona_id" not in fake_suite.chats[1]


def test_a_persona_the_suite_refuses_ends_the_turn_with_its_sentence(
        auth_client, fake_suite, library, engine_for_worker):
    fake_suite.chat_status = httpx.Response(404, json={"detail": {
        "code": "not_found", "message": "persona not found"}})
    done = run(auth_client, prompt="Open the film", persona_id="gone")
    assert done["status"] == "error" and "persona not found" in done["error"]
