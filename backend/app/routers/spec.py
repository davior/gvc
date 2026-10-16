"""The VideoSpec format itself: check a document, and describe the schema."""

from typing import Any

from fastapi import APIRouter, Body

from app.auth import CurrentUser
from app.schemas import DataResponse
from app.schemas_projects import Validation
from app.spec.model import VideoSpec, dump_spec
from app.spec.validation import parse_spec

router = APIRouter()


@router.post("/validate", response_model=DataResponse[Validation])
def validate(_user: CurrentUser, spec: Any = Body(...)) -> DataResponse[Validation]:
    """Check a spec without saving it, for the editor's live feedback.

    Always 200: an invalid spec is the answer to the question, not a failed request.
    The body is the spec itself, not wrapped, so anything at all can be pasted in.
    """
    parsed, issues = parse_spec(spec)
    if parsed is None:
        return DataResponse(data=Validation(valid=False, issues=issues))
    return DataResponse(data=Validation(valid=True, spec=dump_spec(parsed)))


@router.get("/schema", response_model=DataResponse[dict])
def schema(_user: CurrentUser) -> DataResponse[dict]:
    """The JSON Schema of the current spec version.

    The source the editor reads its limits from (a slider's range is the field's `ge` /
    `le`), so the frontend and backend cannot drift apart the way Notes' did.
    """
    return DataResponse(data=VideoSpec.model_json_schema(by_alias=True))
