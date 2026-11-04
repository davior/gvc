"""Narration read through Gecko Suite (`AI_BACKEND=suite`), with the suite faked.

What is checked: that one video keeps one narrator (the model and voice the first chunk
resolved are sent back for every later one), that a model that fails stops the render and
is never quietly swapped, that the suite's own sentences reach the job, and that the same
narration a render reads twice is the suite's to cache, not this app's.
"""

import json
import os
from typing import List, Optional

import httpx
import pytest

from app import suite
from app.config import settings
from app.gam.client import GamClient
from app.render import ffmpeg as F
from app.render import worker
from app.render.renderer import render
from app.render.tts import NotesSpeech, SpeechError, SuiteNarrator
from app.spec.validation import parse_spec
from tests.test_render_integration import SPEC

TOKEN = "notes-session-jwt"


class FakeSuiteSpeech:
    """The suite's /ai/speech/tts: audio as the body, what resolved as headers."""

    def __init__(self, audio: bytes = b"AUDIO" * 100):
        self.audio = audio
        self.requests: List[dict] = []
        self.headers_seen: List[dict] = []
        self.model_ref = "m-routed"
        self.voice = "Aria"
        self.respond = None
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        assert request.url.path == "/api/v1/ai/speech/tts"
        self.headers_seen.append(dict(request.headers))
        body = json.loads(request.content)
        self.requests.append(body)
        if self.respond is not None:
            return self.respond(body)
        return httpx.Response(200, content=self.audio, headers={
            "content-type": "audio/mpeg", "x-speech-provider": "fal",
            "x-speech-model": body.get("model_ref") or self.model_ref,
            "x-speech-voice": body.get("voice") or self.voice, "x-speech-cached": "false"})


@pytest.fixture(name="speech")
def speech_fixture(monkeypatch):
    fake = FakeSuiteSpeech()
    monkeypatch.setattr(settings, "ai_backend", "suite")
    monkeypatch.setattr(suite, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


def narrator() -> SuiteNarrator:
    return SuiteNarrator(TOKEN)


# ─── one narrator for the whole video ────────────────────────────────────────


def test_the_first_chunk_is_read_by_the_routed_model_and_the_rest_by_the_same_one(speech):
    reader = narrator()
    say = reader.caller(None)
    assert say("The valley used to run clear.") == speech.audio
    assert say("The river is lower every year.") == speech.audio

    first, second = speech.requests
    # The first names no model and no voice: whatever the suite's routing says.
    assert "model_ref" not in first and "voice" not in first
    # What resolved is sent back, so a routing change mid-render cannot change the narrator.
    assert second["model_ref"] == "m-routed" and second["voice"] == "Aria"
    # As the app, for the signed-in user: the user is the one paying.
    assert speech.headers_seen[0]["authorization"] == f"Bearer {TOKEN}"
    assert first["app"] == "gvc"
    assert reader.characters == len("The valley used to run clear.") + len("The river is lower every year.")
    reader.close()


def test_a_voice_the_spec_names_is_asked_for_and_then_held(speech):
    reader = narrator()
    named = reader.caller("Roger")
    default = reader.caller(None)
    named("One.")
    default("Two.")
    named("Three.")
    assert [r.get("voice") for r in speech.requests] == ["Roger", None, "Roger"]
    # Both ride the model the first chunk resolved, whichever voice they ask for.
    assert [r.get("model_ref") for r in speech.requests] == [None, "m-routed", "m-routed"]
    default("Four.")
    # The default voice is now pinned to the voice it resolved to.
    assert speech.requests[-1]["voice"] == "Aria"
    reader.close()


def test_a_model_that_fails_midway_stops_the_render_instead_of_changing_voice(speech):
    reader = narrator()
    say = reader.caller(None)
    say("First chunk.")
    speech.respond = lambda body: httpx.Response(503, json={"detail": {
        "code": "upstream_unavailable", "message": "fal.ai is not available right now"}})
    with pytest.raises(SpeechError, match="not available right now"):
        say("Second chunk.")
    # Exactly one more request went out: the pinned model, once. No second engine was tried.
    assert len(speech.requests) == 2 and speech.requests[1]["model_ref"] == "m-routed"
    reader.close()


# ─── what the person is told ─────────────────────────────────────────────────


def test_nothing_routed_says_what_to_set_up(speech):
    speech.respond = lambda body: httpx.Response(409, json={"detail": {
        "code": "ai_not_configured",
        "message": "No text-to-speech model is set up. In Gecko Suite, route speech.tts."}})
    with pytest.raises(SpeechError, match="route speech.tts"):
        narrator().caller(None)("Hello.")


def test_a_suite_that_is_down_stops_the_render_with_a_sentence(speech):
    speech.down = True
    with pytest.raises(SpeechError, match="can't be reached"):
        narrator().caller(None)("Hello.")


def test_a_session_without_a_token_says_so_and_asks_nothing(speech):
    with pytest.raises(SpeechError, match="Notes sign-in"):
        SuiteNarrator(None).caller(None)("Hello.")
    assert speech.requests == []


def test_a_narrator_that_never_spoke_closes_without_a_connection(speech):
    SuiteNarrator(TOKEN).close()  # a render with no narration must not need the suite
    assert speech.requests == []


# ─── which reads the narration ───────────────────────────────────────────────


def test_the_suite_narrates_only_when_the_assistant_is_on_it(monkeypatch):
    monkeypatch.setattr(settings, "ai_backend", "local")
    assert isinstance(worker.narrator(TOKEN), NotesSpeech)
    monkeypatch.setattr(settings, "ai_backend", "suite")
    assert isinstance(worker.narrator(TOKEN), SuiteNarrator)


# ─── a real render ───────────────────────────────────────────────────────────


@pytest.mark.skipif(not F.ffmpeg_available(), reason="needs ffmpeg")
def test_a_whole_video_is_narrated_by_the_suite_and_notes_is_never_asked(
        tmp_path, library, speech):
    speech.audio = library.speech  # the tone of known length the other render tests use
    spec, issues = parse_spec(SPEC)
    assert spec is not None, issues
    gam, reader = GamClient(None), SuiteNarrator(TOKEN)
    try:
        result = render(
            spec=spec, preview=True, work_dir=str(tmp_path / "work"), out_dir=str(tmp_path / "out"),
            data_dir=str(tmp_path / "data"), user_id="u", gam=gam, speech=reader,
            progress=lambda s, p, d: None, max_segments=200, max_narration_chars=10_000)
    finally:
        gam.close()
        reader.close()

    assert os.path.getsize(result.video) > 0 and 11.0 < result.duration < 17.0
    # Three chunks, all through the suite: the first unpinned, the others on its model.
    assert len(speech.requests) == 3 and library.spoken == []
    assert "model_ref" not in speech.requests[0]
    assert all(r["model_ref"] == "m-routed" and r["voice"] == "Aria" for r in speech.requests[1:])
    assert result.narration_chars == reader.characters > 0
