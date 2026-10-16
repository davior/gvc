"""Request and response bodies for renders."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class RenderCreate(BaseModel):
    # A preview renders at 480p and draws placeholders as slates; a full render
    # refuses them.
    preview: bool = True


class RenderRead(BaseModel):
    id: str
    project_id: str
    version: int
    preview: bool
    status: str
    stage: str
    progress: int
    detail: str
    error: Optional[str] = None
    warnings: List[str] = []
    duration: Optional[float] = None
    size_bytes: Optional[int] = None
    narration_chars: int = 0
    # Signed and short-lived: a <video> element cannot send an Authorization header.
    video_url: Optional[str] = None
    subtitles_url: Optional[str] = None
    poster_url: Optional[str] = None
    # Chapters and credits to paste where the video is published.
    description: Optional[str] = None
    # Set once the render is saved to GAM: the asset, and its page there.
    gam_asset_id: Optional[str] = None
    gam_asset_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EstimateRead(BaseModel):
    seconds: float
    seconds_is_floor: bool
    narration_chars: int
    blocks_render: List[str]
    blocks_preview: List[str]
