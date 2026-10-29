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
    # What GAM says an audio file is: music | speech | sfx, null when not known (or GAM
    # predates gam#49). Kept beside `music`, not in it: a voice memo has a kind and no
    # profile, and the kind is what keeps it out of a soundtrack.
    audio_kind: Optional[str] = None


class GamVersion(BaseModel):
    """One standard-resolution file of a GAM video: its 1080p, its 720p (gam#56).

    The same video as the asset's own file, timeline included, at another size. GVC
    renders from whichever is the best match for the output frame (`render/media.py`).
    """

    id: str
    # The standard size, as the frame's short side in pixels: 1080 is 1920x1080 and
    # 1080x1920 alike. `width`/`height` are what the file really is.
    short_side: int
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: int = 0
    file_url: Optional[str] = None


class GamHit(BaseModel):
    asset: GamAssetRead
    score: float = 0.0
    snippet: str = ""
    # The moment that matched, in seconds into the asset. Both null for a hit on the
    # file's name or description rather than on something said in it.
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    # How many other moments in the same asset also matched. GAM returns one row per
    # asset, its best moment, so this is the only sign that the rest is worth reading.
    other_matches: int = 0


class GamWord(BaseModel):
    text: str
    start_time: float
    end_time: float


class GamSegment(BaseModel):
    text: str
    start_time: float
    end_time: float
    speaker: Optional[int] = None
    # Corrected by hand in GAM. The words keep their timings but may no longer spell the
    # text, so an edited segment is read as its text.
    edited: bool = False
    words: List[GamWord] = Field(default_factory=list)


class GamTranscript(BaseModel):
    asset_id: str
    language: Optional[str] = None
    segments: List[GamSegment] = Field(default_factory=list)


class GamWaveform(BaseModel):
    """What the audio player draws its scrub bar from: peak amplitudes in 0..1, evenly
    over `duration` seconds. GAM computes it on first view and caches it (gam#54)."""

    duration: float
    peaks: List[float]


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
