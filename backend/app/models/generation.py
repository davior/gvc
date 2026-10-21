"""One generation asked of GAM for a `generate` placeholder.

The job itself runs in GAM; this row is how GVC follows it. Nothing here needs a token
at rest or a worker of GVC's own: each read of a project's generations asks GAM about
the unfinished ones with the reader's token, so a generation started and left finishes
in GAM and is caught up the next time anyone looks, after a restart included.
"""

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from app.clock import utcnow


class Generation(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    # None while it belongs to an assistant draft not yet made into a project.
    project_id: Optional[str] = Field(default=None, index=True)
    turn_id: Optional[str] = Field(default=None, index=True)
    # The placeholder it fills, by its key in the spec's asset registry.
    asset_key: str
    gam_job_id: str = Field(index=True)
    kind: str                          # text_to_image | image_to_image | image_to_video
    prompt: str
    model_label: str = ""
    params: str = "{}"                 # JSON, as sent to GAM
    # queued | processing | done | error | cancelled (GAM's job statuses)
    status: str = "queued"
    stage: str = ""
    progress: int = 0
    detail: str = ""
    error: Optional[str] = None
    result_ids: str = "[]"             # JSON: GAM asset ids, in output order
    # The output in the placeholder now; None until one has been put there.
    used_id: Optional[str] = None
    estimate: Optional[float] = None   # list price, USD
    # A clip made from a picture generated for it: while the picture is being made,
    # the clip's run (JSON: model_id, model_label, prompt, params), started from the
    # picture by `refresh` and then cleared. `picture_id` is the picture, once made.
    then: Optional[str] = None
    picture_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
