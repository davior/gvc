"""Narration, read through Gecko Notes' speech.

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

from app import outbound
from app.config import settings


class SpeechError(Exception):
    pass


class NotesSpeech:
    def __init__(self, token: Optional[str]):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = outbound.client(settings.notes_base_url, timeout=120, headers=headers)
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
