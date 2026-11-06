"""Narration, read through Gecko Suite (`AI_BACKEND=suite`) or, as before, Gecko Notes.

`NotesSpeech` is the original. `SuiteNarrator` reads through the suite's `speech.tts`, which
holds the voice, the provider key and the audio cache; see its docstring for what differs.

Notes' version, as written:

Voices, provider keys and the TTS cache live in Notes, so GVC asks Notes to read each
chunk as the signed-in user (open decision 3 in the plan of attack). Notes' cache is
keyed on provider, voice and text, which is what makes a preview followed by a full
render bill for the narration once.

One video must not change voice partway through. The first chunk is sent with
`provider: "auto"`; Notes answers with the engine and voice it resolved
(`X-Speech-Provider` / `X-Speech-Voice`, gecko-notes#211), and every later chunk
sends those back. A transient failure then fails the render, instead of one chunk
quietly arriving in another engine's voice.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import httpx
from gecko_suite_client import SuiteError, SuiteSpeech, SuiteUnavailable

from app import outbound, suite
from app.config import settings
from app.providers.base import ProviderError


class SpeechError(Exception):
    pass


class NotesSpeech:
    def __init__(self, token: Optional[str]):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = outbound.client(settings.notes_url, timeout=120, headers=headers)
        self.provider: Optional[str] = None
        # The voice each requested one resolved to (None: the account's).
        self._voices: Dict[Optional[str], Optional[str]] = {}
        self.characters = 0

    def close(self) -> None:
        self._http.close()

    def _say(self, text: str, voice: Optional[str]) -> bytes:
        pinned = self._voices.get(voice, voice)
        body = {"text": text, "provider": self.provider or "auto", "voice": pinned}
        try:
            response = self._http.post("/api/settings/speech/tts", json=body)
        except httpx.HTTPError as exc:
            raise SpeechError("Could not reach Gecko Notes to read the narration") from exc
        if response.status_code == 401:
            raise SpeechError("Gecko Notes did not accept your session for reading the "
                              "narration. Its JWT_SECRET_KEY may differ from GVC's.")
        if response.status_code != 200:
            try:
                detail = response.json().get("detail")
                message = detail.get("message") if isinstance(detail, dict) else str(detail)
            except ValueError:
                message = response.text[:200]
            raise SpeechError(f"Gecko Notes could not read the narration: {message}")
        provider = response.headers.get("x-speech-provider")
        if not provider:
            # A Notes from before #211 ignores the fields and reads in whatever
            # `model` defaults to, with nothing to pin. Better to say so than to
            # render a video that may change voice.
            raise SpeechError("Gecko Notes needs updating to read narration for a video "
                              "(gecko-notes#211).")
        if self.provider is None:
            self.provider = provider
        if voice not in self._voices:
            self._voices[voice] = response.headers.get("x-speech-voice") or None
        self.characters += len(text)
        return response.content

    def caller(self, voice: Optional[str]) -> Callable[[str], bytes]:
        """A `text -> audio bytes` callable for `narration.synthesize_shot`."""
        return lambda text: self._say(text, voice)


class SuiteNarrator:
    """The same narration, read by Gecko Suite. Interface-compatible with `NotesSpeech`.

    **Where the voice comes from.** Video Creator has no voice setting of its own, so a
    voice the spec does not name is the one the suite's `speech.tts` routing carries (its
    model's default voice), set once on the suite's Providers screen.

    **One video, one voice.** The first chunk is read by whatever `speech.tts` resolves to,
    and the suite answers with the model and voice it used. Every later chunk sends those
    back, so a routing change made while a render runs cannot change the narrator partway.
    And a pinned model that fails fails the render: unlike Notes' `auto`, the suite never
    falls back to another engine for one chunk, which handed back a narrator that changed
    voice halfway through.

    **Billed once.** The suite caches audio by words and voice, so the preview and the full
    render read the narration once. `characters` still counts what was read, cached or not,
    because it is the render's own record of how much narration it had.

    The connection is opened at the first chunk, not at construction, so a session with no
    token stops the render with a sentence, from inside it, like any other speech failure.
    """

    def __init__(self, token: Optional[str]):
        self._token = token
        self._connection = None
        self._speech: Optional[SuiteSpeech] = None
        self.model_ref: Optional[str] = None
        # The voice each requested one resolved to (None: the model's default).
        self._voices: Dict[Optional[str], Optional[str]] = {}
        self.characters = 0

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()

    def _open(self) -> SuiteSpeech:
        if self._speech is None:
            try:
                self._connection = suite.client(self._token)
            except ProviderError as exc:
                raise SpeechError(str(exc)) from exc
            self._speech = SuiteSpeech(self._connection, app=suite.APP)
        return self._speech

    def _say(self, text: str, voice: Optional[str]) -> bytes:
        pinned = self._voices.get(voice, voice)
        try:
            spoken = self._open().speak(text, voice=pinned, model_ref=self.model_ref)
        except SuiteUnavailable as exc:
            raise SpeechError("Gecko Suite can't be reached to read the narration. Try the "
                              "render again in a moment.") from exc
        except SuiteError as exc:
            raise SpeechError(f"Gecko Suite could not read the narration: {exc.message}") from exc
        if self.model_ref is None:
            self.model_ref = spoken.model_ref or None
        if voice not in self._voices:
            self._voices[voice] = spoken.voice or None
        self.characters += len(text)
        return spoken.audio

    def caller(self, voice: Optional[str]) -> Callable[[str], bytes]:
        """A `text -> audio bytes` callable for `narration.synthesize_shot`."""
        return lambda text: self._say(text, voice)
