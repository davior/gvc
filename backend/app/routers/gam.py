"""Searching and reading GAM, the media library, as the signed-in user."""

from typing import Iterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import CallerToken, CurrentUser
from app.gam.client import GamClient
from app.schemas import DataResponse, ListResponse
from app.schemas_gam import (
    AssetLookup, AssetLookupResult, GamAssetRead, GamPlaylist, GamPlaylistDetail, GamSearch, GamWaveform,
    ImageImport, PlaylistCreate, PlaylistItemsAdd,
)

router = APIRouter()


def get_gam(_user: CurrentUser, token: CallerToken) -> Iterator[GamClient]:
    """A GAM client acting as the caller. Depends on `current_user` first, so a token
    is only ever forwarded after this app has verified it."""
    client = GamClient(token)
    try:
        yield client
    finally:
        client.close()


@router.get("/search", response_model=GamSearch)
def search(
    q: str = Query(default="", max_length=500),
    # What can go on screen or under it. GAM also holds documents, which a video has
    # no use for, so they are not offered.
    type: Optional[Literal["image", "video", "audio"]] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    gam: GamClient = Depends(get_gam),
) -> GamSearch:
    if not q.strip():
        return GamSearch(data=[], total=0, query="")
    result = gam.search(q, asset_type=type, limit=limit)
    if type is None:
        # Without a type filter GAM returns documents too; keep the three media kinds.
        result.data = [h for h in result.data if h.asset.asset_type in ("image", "video", "audio")]
        result.total = len(result.data)
    return result


@router.post("/assets/lookup", response_model=DataResponse[AssetLookupResult])
def lookup(body: AssetLookup, gam: GamClient = Depends(get_gam)) -> DataResponse[AssetLookupResult]:
    """Names, thumbnails and fresh signed URLs for the GAM assets a spec uses.

    One GET per id, in sequence: a project uses a handful, and GAM has no batch read.
    Asked for on each page load, because the signed URLs expire.
    """
    assets = {asset_id: gam.get_asset(asset_id) for asset_id in dict.fromkeys(body.ids)}
    return DataResponse(data=AssetLookupResult(assets=assets))


@router.post("/import-image", response_model=DataResponse[GamAssetRead])
def import_image(body: ImageImport, gam: GamClient = Depends(get_gam)) -> DataResponse[GamAssetRead]:
    """File a picture found on the web in the caller's library, and return the asset.

    GAM fetches it (and refuses what it should not fetch), so this app never downloads
    from an address the person or a model chose.
    """
    asset = gam.import_image(body.image_url, page_url=body.page_url, title=body.title,
                             description=body.description)
    return DataResponse(data=asset)


@router.get("/assets/{asset_id}/peaks", response_model=DataResponse[GamWaveform])
def peaks(asset_id: str, gam: GamClient = Depends(get_gam)) -> DataResponse[GamWaveform]:
    """The waveform an audio player in the editor scrubs on, from GAM's cache.

    Through this backend like every other GAM read, so the browser never needs GAM's
    address or a CORS rule for it (GAM-5).
    """
    waveform = gam.peaks(asset_id)
    if waveform is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "waveform_unavailable", "message": "The asset library has no waveform for this"},
        )
    return DataResponse(data=waveform)


def _found(playlist: Optional[GamPlaylistDetail], what: str = "playlist") -> GamPlaylistDetail:
    if playlist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail={"code": "not_found", "message": f"No such {what} in GAM."})
    return playlist


@router.get("/playlists", response_model=ListResponse[GamPlaylist])
def playlists(q: str = Query(default="", max_length=200),
              gam: GamClient = Depends(get_gam)) -> ListResponse[GamPlaylist]:
    """The caller's GAM playlists, newest edit first: to start a video from one, to take
    footage from, or to add to. `q` keeps those whose name or description holds it."""
    rows = gam.playlists(q)
    return ListResponse(data=rows, total=len(rows), limit=len(rows), offset=0)


@router.post("/playlists", response_model=DataResponse[GamPlaylistDetail],
             status_code=status.HTTP_201_CREATED)
def create_playlist(body: PlaylistCreate,
                    gam: GamClient = Depends(get_gam)) -> DataResponse[GamPlaylistDetail]:
    """A new playlist in the caller's library, with its first items if any.

    A playlist is GAM's, not part of a video: making one here changes nothing in any
    project, the same as making it in GAM.
    """
    made = gam.create_playlist(body.name.strip(), body.description,
                               [i.model_dump(exclude_none=True) for i in body.items])
    return DataResponse(data=made)


@router.get("/playlists/{playlist_id}", response_model=DataResponse[GamPlaylistDetail])
def playlist(playlist_id: str, gam: GamClient = Depends(get_gam)) -> DataResponse[GamPlaylistDetail]:
    return DataResponse(data=_found(gam.playlist(playlist_id)))


@router.post("/playlists/{playlist_id}/items", response_model=DataResponse[GamPlaylistDetail],
             status_code=status.HTTP_201_CREATED)
def add_playlist_items(playlist_id: str, body: PlaylistItemsAdd,
                       gam: GamClient = Depends(get_gam)) -> DataResponse[GamPlaylistDetail]:
    """Items added to a playlist, all or none, and the playlist as it now is."""
    items = [i.model_dump(exclude_none=True) for i in body.items]
    return DataResponse(data=_found(gam.add_playlist_items(playlist_id, items, body.position)))


@router.delete("/playlists/{playlist_id}/items/{item_id}",
               response_model=DataResponse[GamPlaylistDetail])
def remove_playlist_item(playlist_id: str, item_id: str,
                         gam: GamClient = Depends(get_gam)) -> DataResponse[GamPlaylistDetail]:
    """One item out of a playlist. The asset stays in the library."""
    return DataResponse(data=_found(gam.remove_playlist_item(playlist_id, item_id),
                                    "playlist or item"))
