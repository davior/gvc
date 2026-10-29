"""Calling GAM as the signed-in user.

GVC forwards the caller's own Notes-issued token, so GAM sees the same user it would
see from its own frontend: same library, same ownership checks. No service account,
and nothing GVC could reach that the user could not.

Every failure becomes a `GamError` with a code, which `main.py` turns into a 502 in the
suite's error shape. A 502 rather than passing GAM's status through: from the browser's
point of view GVC is the server, and GVC's upstream failed.
"""

from __future__ import annotations

import logging
from typing import IO, Any, Dict, List, Optional

import httpx

from app import outbound
from app.config import settings
from app.schemas_gam import GamAssetRead, GamHit, GamMusic, GamSearch, GamTranscript, GamWaveform

logger = logging.getLogger(__name__)

# See `GamClient.peaks`.
PEAKS_TIMEOUT_SECONDS = 120


class GamError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _absolute(url: Optional[str]) -> Optional[str]:
    """GAM's media URLs are relative to GAM (`/media/<key>?exp=…&sig=…`)."""
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return settings.gam_base_url.rstrip("/") + url


def to_asset(raw: Dict[str, Any]) -> GamAssetRead:
    return GamAssetRead(
        id=raw["id"],
        name=raw.get("name") or "",
        asset_type=raw.get("asset_type") or "",
        duration_seconds=raw.get("duration_seconds"),
        width=raw.get("width"),
        height=raw.get("height"),
        file_url=_absolute(raw.get("file_url")),
        thumb_url=_absolute(raw.get("thumb_url")),
        credit=raw.get("credit") or "",
        page_url=f"{settings.gam_base_url.rstrip('/')}/a/{raw['id']}",
        size_bytes=raw.get("size_bytes") or 0,
        parent_asset_id=raw.get("parent_asset_id"),
        in_point=raw.get("in_point"),
        out_point=raw.get("out_point"),
        missing=bool(raw.get("missing")),
        music=_music(raw),
        audio_kind=raw.get("audio_kind") if raw.get("audio_kind") in ("music", "speech", "sfx") else None,
    )


def _music(raw: Dict[str, Any]) -> Optional[GamMusic]:
    """GAM's flat `music_*` fields as one object, or None when none of them says anything.

    None rather than an empty profile so "GAM knows nothing about this track" and "GAM
    is older than the profile" read the same, and nothing downstream has to tell an
    empty object from a missing one.
    """
    def terms(name: str) -> List[str]:
        value = raw.get(name)
        return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []

    music = GamMusic(
        genres=terms("music_genres"),
        moods=terms("music_moods"),
        instruments=terms("music_instruments"),
        bpm=raw.get("music_bpm"),
        key=raw.get("music_key"),
        vocals=raw.get("music_vocals"),
        energy=raw.get("music_energy"),
    )
    if not (music.genres or music.moods or music.instruments) and all(
        value is None for value in (music.bpm, music.key, music.vocals, music.energy)
    ):
        return None
    return music


class GamClient:
    def __init__(self, token: Optional[str]):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = outbound.client(
            settings.gam_base_url, timeout=settings.gam_timeout_seconds, headers=headers
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise GamError("gam_unavailable", "The asset library took too long to answer") from exc
        except httpx.HTTPError as exc:
            logger.warning("GAM unreachable at %s: %s", settings.gam_base_url, exc)
            raise GamError("gam_unavailable", "Could not reach the asset library") from exc

        if response.status_code == 401:
            # The user is signed in here, so GAM refusing the same token means the two
            # apps disagree about JWT_SECRET_KEY: an operator's problem, said as one.
            raise GamError(
                "gam_rejected_session",
                "The asset library did not accept your session. GVC and GAM probably "
                "have different JWT_SECRET_KEY values.",
            )
        if response.status_code >= 500:
            raise GamError("gam_unavailable", f"The asset library failed ({response.status_code})")
        return response

    @staticmethod
    def _detail(response: httpx.Response) -> tuple[str, str]:
        try:
            detail = response.json().get("detail") or {}
        except ValueError:
            detail = {}
        if isinstance(detail, dict):
            return detail.get("code") or "gam_error", detail.get("message") or response.text[:200]
        return "gam_error", str(detail)

    def search(self, query: str, *, asset_type: Optional[str] = None, limit: int = 30) -> GamSearch:
        params: Dict[str, Any] = {"q": query, "limit": limit}
        if asset_type:
            params["asset_type"] = asset_type
        response = self._request("GET", "/api/search", params=params)
        if response.status_code != 200:
            code, message = self._detail(response)
            raise GamError(code, message, status_code=400 if response.status_code < 500 else 502)
        body = response.json()
        return GamSearch(
            data=[
                GamHit(
                    asset=to_asset(hit["asset"]),
                    score=hit.get("score") or 0.0,
                    snippet=hit.get("snippet") or "",
                    start_time=hit.get("start_time"),
                    # Absent from a GAM older than its `end_time` change (gam#36); the
                    # editor then sizes the moment itself.
                    end_time=hit.get("end_time"),
                    other_matches=hit.get("other_matches") or 0,
                )
                for hit in body.get("data", [])
            ],
            total=body.get("total", 0),
            query=body.get("query", query),
            semantic=bool(body.get("semantic")),
            semantic_error=body.get("semantic_error"),
        )

    def get_asset(self, asset_id: str) -> Optional[GamAssetRead]:
        response = self._request("GET", f"/api/assets/{asset_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            code, message = self._detail(response)
            raise GamError(code, message)
        return to_asset(response.json()["data"])

    def transcript(self, asset_id: str) -> Optional[GamTranscript]:
        """Everything said in an asset, with word timings. None for an unknown asset; an
        asset never transcribed comes back with no segments."""
        response = self._request("GET", f"/api/assets/{asset_id}/transcript")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            code, message = self._detail(response)
            raise GamError(code, message)
        return GamTranscript.model_validate(response.json()["data"])

    def peaks(self, asset_id: str) -> Optional[GamWaveform]:
        """An audio asset's waveform, or None if GAM has none to give.

        None covers an unknown asset, one GAM cannot decode, and a GAM older than gam#54,
        which has no such route and answers 404: the player then scrubs on a flat line,
        which is a lesser player rather than an error.

        A longer timeout than every other call. GAM decodes a recording the first time
        anyone asks, which took ~21 s for an hour in testing, so the default 30 s would
        cut off a long interview. Even then nothing is lost: GAM's handler runs to the
        end and caches, so the next open is instant.
        """
        response = self._request("GET", f"/api/assets/{asset_id}/peaks", timeout=PEAKS_TIMEOUT_SECONDS)
        if response.status_code != 200:
            return None
        return GamWaveform.model_validate(response.json()["data"])

    def download(self, file_url: str, sink, *, max_bytes: int) -> int:
        """Stream one of GAM's signed media URLs into `sink`. Returns the bytes written."""
        written = 0
        try:
            with self._http.stream("GET", file_url, timeout=600) as response:
                if response.status_code != 200:
                    raise GamError("gam_media_unavailable",
                                   f"The asset library would not hand over a file ({response.status_code})")
                for chunk in response.iter_bytes(1024 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise GamError("gam_media_too_large", "A file in this video is too large to render")
                    sink.write(chunk)
        except httpx.HTTPError as exc:
            raise GamError("gam_unavailable", "Could not fetch a file from the asset library") from exc
        return written

    def upload(self, filename: str, stream: IO[bytes], content_type: Optional[str], *,
               fields: Optional[Dict[str, str]] = None,
               timeout: Optional[float] = None) -> GamAssetRead:
        """Store one file in the user's library and return it.

        `fields` go along as form fields: a render's `source=gvc_export` and origin ids
        (GAM-3). A GAM without GAM-3 ignores them and stores an ordinary upload.
        """
        response = self._request(
            "POST",
            "/api/assets",
            files={"files": (filename, stream, content_type or "application/octet-stream")},
            data=fields or None,
            **({"timeout": timeout} if timeout else {}),
        )
        if response.status_code not in (200, 201):
            code, message = self._detail(response)
            raise GamError(code, message, status_code=502)
        body = response.json()
        created = body.get("created") or []
        if not created:
            # GAM's partial success: a 201 that stored nothing names why per file.
            rejected = (body.get("rejected") or [{}])[0]
            raise GamError(rejected.get("code") or "gam_error",
                           rejected.get("message") or "The asset library did not store the file")
        return to_asset(created[0])

    def update(self, asset_id: str, changes: Dict[str, Any]) -> Optional[GamAssetRead]:
        """Edit an asset's fields (its name, its description). None: it is gone."""
        response = self._request("PATCH", f"/api/assets/{asset_id}", json=changes)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            code, message = self._detail(response)
            raise GamError(code, message)
        return to_asset(response.json()["data"])

    # ── generation (GAM's M8) ────────────────────────────────────────────────
    # GAM runs the generation on fal.ai with the user's own key and keeps the outputs in
    # their library. A job is followed by its id; GVC never talks to fal.

    def _generation_error(self, response: httpx.Response) -> GamError:
        code, message = self._detail(response)
        if code == "fal_key_missing":
            message = ("Generating needs a fal.ai API key in the asset library's settings: "
                       f"{settings.gam_base_url.rstrip('/')}/settings")
        return GamError(code, message, status_code=400 if response.status_code < 500 else 502)

    def generation_models(self) -> List[Dict[str, Any]]:
        response = self._request("GET", "/api/generate/models")
        if response.status_code != 200:
            raise self._generation_error(response)
        return list(response.json().get("data") or [])

    def start_generation(self, *, model_id: str, prompt: str, base_ids: List[str],
                         params: Dict[str, Any]) -> Dict[str, Any]:
        response = self._request("POST", "/api/generate", json={
            "model_id": model_id, "prompt": prompt, "base_asset_ids": base_ids,
            "params": params,
        })
        if response.status_code not in (200, 201, 202):
            raise self._generation_error(response)
        return response.json()["data"]

    def generation_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        response = self._request("GET", f"/api/activity/enrichment/{job_id}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise self._generation_error(response)
        return response.json()["data"]

    def cancel_generation(self, job_id: str) -> None:
        response = self._request("DELETE", f"/api/activity/enrichment/{job_id}")
        if response.status_code not in (200, 204, 404):
            raise self._generation_error(response)
