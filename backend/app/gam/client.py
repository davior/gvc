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
from typing import IO, Any, Dict, Optional

import httpx

from app import outbound
from app.config import settings
from app.schemas_gam import GamAssetRead, GamHit, GamSearch

logger = logging.getLogger(__name__)


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
        parent_asset_id=raw.get("parent_asset_id"),
        in_point=raw.get("in_point"),
        out_point=raw.get("out_point"),
        missing=bool(raw.get("missing")),
    )


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

    def upload(self, filename: str, stream: IO[bytes], content_type: Optional[str]) -> GamAssetRead:
        """Store one file in the user's library and return it."""
        response = self._request(
            "POST",
            "/api/assets",
            files={"files": (filename, stream, content_type or "application/octet-stream")},
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
