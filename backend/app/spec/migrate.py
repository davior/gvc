"""Bringing an older spec up to the current version, on load.

The JSON equivalent of an Alembic revision (the Notes spec doc, open decision 8): one
function per version step, applied in order to raw data *before* validation, so the
model only ever has to understand the current shape. Notes' `POST /api/video/spec`
emits 0.1, and that is what a note pushed into GVC arrives as.
"""

from copy import deepcopy
from typing import Any, Callable, Dict

from app.spec.model import SPEC_VERSION


class SpecVersionError(ValueError):
    """A spec_version this code has no path from: a newer spec, or a typo."""


def _from_0_1(data: Dict[str, Any]) -> Dict[str, Any]:
    # 0.1's source could only be a note, so it carried no `kind`. A source with
    # nothing in it said nothing, and is dropped rather than turned into a note
    # reference to no note.
    source = data.get("source")
    if isinstance(source, dict):
        if any(source.get(k) for k in ("note_id", "note_version_id", "imported_at")):
            data["source"] = {"kind": "note", **source}
        else:
            data.pop("source")
    data["spec_version"] = "0.2"
    return data


# version → the step that takes it to the next one.
_STEPS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "0.1": _from_0_1,
}


def migrate(data: Any) -> Any:
    """Return `data` at the current spec version.

    Anything that is not a dict is passed through untouched for validation to refuse
    with a proper message. A missing `spec_version` is taken as current: a spec typed
    by hand, or pasted from the editor, should not need the boilerplate.
    """
    if not isinstance(data, dict):
        return data
    data = deepcopy(data)
    version = data.get("spec_version", SPEC_VERSION)
    while version != SPEC_VERSION:
        step = _STEPS.get(version)
        if step is None:
            raise SpecVersionError(
                f"spec_version {version!r} is not one this version of GVC can read "
                f"(it reads up to {SPEC_VERSION!r})"
            )
        data = step(data)
        version = data["spec_version"]
    return data
