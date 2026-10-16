"""GAM and Gecko Notes, faked behind one `httpx.MockTransport`.

Installed on `app.outbound.TRANSPORT`, so every client GVC builds talks to these
instead of the network. Records what it was asked, so tests can assert the caller's
token was forwarded and nothing was fetched that should not have been.
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import httpx

GAM = "https://gam.test"
NOTES = "https://notes.test"


def gam_asset(asset_id: str, name: str, asset_type: str = "video", **extra) -> dict:
    return {
        "id": asset_id,
        "name": name,
        "asset_type": asset_type,
        "duration_seconds": 1800.0 if asset_type == "video" else None,
        "file_url": f"/media/{asset_id}.bin?exp=1&sig=x",
        "thumb_url": f"/media/{asset_id}.jpg?exp=1&sig=x",
        "credit": "",
        "missing": False,
        **extra,
    }


@dataclass
class FakeSiblings:
    assets: Dict[str, dict] = field(default_factory=dict)
    hits: List[dict] = field(default_factory=list)
    notes_files: Dict[str, bytes] = field(default_factory=dict)
    requests: List[httpx.Request] = field(default_factory=list)
    # Set to make GAM answer every request with this status.
    gam_status: Optional[int] = None
    gam_down: bool = False
    # GAM media bytes by path ("/media/<key>"), and what Notes' speech says per chunk.
    media_files: Dict[str, bytes] = field(default_factory=dict)
    speech: Optional[bytes] = None
    speech_provider: Optional[str] = "deepgram"
    spoken: List[dict] = field(default_factory=list)
    # Filenames GAM should refuse on upload.
    refuse_uploads: List[str] = field(default_factory=list)
    uploads: List[dict] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(GAM):
            return self._gam(request)
        if url.startswith(NOTES) and request.url.path == "/api/settings/speech/tts":
            body = json.loads(request.content)
            self.spoken.append(body)
            headers = {"content-type": "audio/wav"}
            if self.speech_provider:
                headers["x-speech-provider"] = body["provider"] if body["provider"] != "auto" \
                    else self.speech_provider
                headers["x-speech-voice"] = body.get("voice") or "Rex"
            return httpx.Response(200, content=self.speech or b"", headers=headers)
        if url.startswith(NOTES):
            path = request.url.path
            if path in self.notes_files:
                return httpx.Response(200, content=self.notes_files[path],
                                      headers={"content-type": "image/png"})
            return httpx.Response(404)
        raise AssertionError(f"unexpected outbound request to {url}")

    def _gam(self, request: httpx.Request) -> httpx.Response:
        if self.gam_down:
            raise httpx.ConnectError("refused", request=request)
        if self.gam_status:
            return httpx.Response(self.gam_status, json={"detail": {"code": "x", "message": "y"}})
        path = request.url.path
        if path.startswith("/media/") and path in self.media_files:
            return httpx.Response(200, content=self.media_files[path])
        if path == "/api/search":
            return httpx.Response(200, json={
                "data": self.hits, "total": len(self.hits),
                "query": request.url.params.get("q"), "semantic": False, "semantic_error": None,
            })
        if path.startswith("/api/assets/") and request.method == "GET":
            asset = self.assets.get(path.rsplit("/", 1)[-1])
            if asset is None:
                return httpx.Response(404, json={"detail": {"code": "not_found", "message": "gone"}})
            return httpx.Response(200, json={"data": asset})
        if path == "/api/assets" and request.method == "POST":
            body = request.read()
            filename = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            if filename in self.refuse_uploads:
                return httpx.Response(400, json={"detail": {
                    "code": "unsupported_type", "message": "That file type is not supported"}})
            new_id = f"gam-{len(self.uploads) + 1}"
            asset = gam_asset(new_id, filename, "image")
            self.assets[new_id] = asset
            self.uploads.append({"filename": filename, "size": len(body)})
            return httpx.Response(201, json={"created": [asset], "rejected": []})
        return httpx.Response(404)

    def gam_requests(self) -> List[httpx.Request]:
        return [r for r in self.requests if str(r.url).startswith(GAM)]


def hit(asset: dict, *, start=None, end=None, snippet="") -> dict:
    data = {"asset": asset, "score": 0.03, "snippet": snippet, "start_time": start,
            "segment_id": "seg" if start is not None else None, "sources": ["keyword"],
            "other_matches": 0}
    if end is not None:
        data["end_time"] = end
    return data


def dumps(value) -> str:
    return json.dumps(value)
