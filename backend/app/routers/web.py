"""Pictures from the web, for a background or an overlay: found through Gecko Suite.

Finding is all this does. A picture found here is shown to the person as a thumbnail
from the site, and only the one they choose is fetched, by GAM, as an asset
(`routers/gam.py::import_image`). A video never refers to a web address.
"""

from contextlib import closing
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from gecko_suite_client import SuiteError, SuiteUnavailable
from pydantic import BaseModel

from app import suite
from app.auth import CallerToken, CurrentUser
from app.providers.base import ProviderError
from app.schemas import ListResponse

router = APIRouter()

MAX_IMAGES = 30


class WebImage(BaseModel):
    image_url: str
    page_url: Optional[str] = None
    title: str = ""
    thumbnail_url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    description: str = ""


def _refuse(code: str, message: str, status_code: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.get("/images", response_model=ListResponse[WebImage])
def images(
    _user: CurrentUser,
    token: CallerToken,
    q: str = Query(default="", max_length=500),
    project_id: Optional[str] = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=MAX_IMAGES),
) -> ListResponse[WebImage]:
    if not q.strip():
        return ListResponse(data=[], total=0, limit=limit, offset=0)
    if not suite.enabled():
        # The suite holds the search keys; without it there is no web to search. The rest
        # of the editor, the library's own search included, is unaffected.
        raise _refuse("web_search_unavailable",
                      "Searching the web for pictures needs Gecko Suite (AI_BACKEND=suite).")
    try:
        with closing(suite.client(token)) as connection:
            rows = suite.image_search(connection, q.strip(), project_id, count=limit)
    except ProviderError as exc:
        raise _refuse("web_search_unavailable", str(exc))
    except SuiteUnavailable:
        raise _refuse("suite_unavailable", "Gecko Suite can't be reached right now, so the web "
                      "can't be searched. The library's own search still works.",
                      status.HTTP_503_SERVICE_UNAVAILABLE)
    except SuiteError as exc:
        # The suite's sentences are written to be shown ("Set up Tavily, Brave or SearXNG…").
        raise _refuse(exc.code, exc.message,
                      exc.status if 400 <= exc.status < 500 else status.HTTP_502_BAD_GATEWAY)
    data = [WebImage(**{k: r.get(k) for k in WebImage.model_fields if r.get(k) is not None})
            for r in rows if isinstance(r, dict) and r.get("image_url")]
    return ListResponse(data=data, total=len(data), limit=limit, offset=0)
