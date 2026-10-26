"""GAM's assets and search hits, in GVC's own shape.

Normalised rather than passed through, so a field GAM renames breaks this file and its
tests instead of every screen that shows a thumbnail. Only what GVC uses is kept.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class GamMusic(BaseModel):
    """What a track sounds like, from GAM's music profile (gam#46).

    The one thing that lets a soundtrack be chosen for a scene rather than by its title.
    Null on the asset when GAM knows nothing about it, or is older than the profile.
    """

    genres: List[str] = Field(default_factory=list)
    moods: List[str] = Field(default_factory=list)
    instruments: List[str] = Field(default_factory=list)
    bpm: Optional[float] = None
    # As GAM stores it: "Am", "A minor" and Camelot "8A" are all left as written.
    key: Optional[str] = None
    # Null is "not known", which is not False ("instrumental"). Treating the two as one
    # would put songs with words under narration.
    vocals: Optional[bool] = None
    energy: Optional[str] = None  # low | medium | high


class GamAssetRead(BaseModel):
    id: str
    name: str
    asset_type: str
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    # Absolute and signed by GAM: usable directly in <img>/<video>, expiring after
    # GAM's media TTL, so fetched per page load and never stored in a spec.
    file_url: Optional[str] = None
    thumb_url: Optional[str] = None
    credit: str = ""
    # GAM's own page for the asset, for a link that opens it in the library. Built from
    # `GAM_BASE_URL`, not signed: opening it is GAM's login, not GVC's.
    page_url: Optional[str] = None
    # The file's size, which is what tells the render cache a copy is still current.
    size_bytes: int = 0
    # A GAM clip has no file of its own: it is its parent's bytes between these points.
    parent_asset_id: Optional[str] = None
    in_point: Optional[float] = None
    out_point: Optional[float] = None
    missing: bool = False
    music: Optional[GamMusic] = None


class GamHit(BaseModel):
    asset: GamAssetRead
    score: float = 0.0
    snippet: str = ""
    # The moment that matched, in seconds into the asset. Both null for a hit on the
    # file's name or description rather than on something said in it.
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class GamSearch(BaseModel):
    data: List[GamHit]
    total: int
    query: str
    # Whether GAM's meaning-based half ran. "No results" means less when it did not.
    semantic: bool = False
    semantic_error: Optional[str] = None


class AssetLookup(BaseModel):
    ids: List[str] = Field(default_factory=list, max_length=200)


class AssetLookupResult(BaseModel):
    # Null for an id GAM no longer has (deleted, or not this user's).
    assets: Dict[str, Optional[GamAssetRead]]
