"""Turning raw JSON into a VideoSpec, or into errors a person can act on.

Pydantic's own errors name a location like `segments.2.narration.beats.0.text`, plus
noise from discriminated unions (`assets.a_map.gam.id`, where `gam` is the union arm,
not a key in the document). The editor needs a path it can point at in the JSON, so the
union tags are stripped and the rest kept as a list of keys and indexes.
"""

from typing import Any, List, Tuple, Union

from pydantic import BaseModel, ValidationError

from app.spec.migrate import SpecVersionError, migrate
from app.spec.model import VideoSpec

PathPart = Union[str, int]

# The discriminator values Pydantic inserts into a location. None of them can be a
# real key at the position they appear in, because each sits directly under a union
# field — but a key like `assets.notes` could exist, so a tag is only dropped when it
# immediately follows a union-valued field.
_UNION_TAGS = {"notes", "gam", "generate", "search", "note", "brief",
               "quote", "code", "text", "lower_third", "image", "waveform",
               "AnchorRef", "literal['video_start','video_end']"}
_UNION_PARENTS = {"source", "overlays", "start", "end", "from", "to"}


class SpecIssue(BaseModel):
    path: List[PathPart]
    message: str


def _clean_path(loc: Tuple[Any, ...]) -> List[PathPart]:
    path: List[PathPart] = []
    for i, part in enumerate(loc):
        if isinstance(part, str) and part in _UNION_TAGS and i > 0:
            parent = loc[i - 1]
            # A tag directly after an asset key, or a union field, or a list index
            # inside `overlays`.
            if (len(loc) > 1 and loc[0] == "assets" and i == 2) or parent in _UNION_PARENTS \
                    or (isinstance(parent, int) and i > 1 and loc[i - 2] in _UNION_PARENTS):
                continue
        if isinstance(part, str) and part.startswith("function-"):
            continue
        path.append(part)
    return path


def _dedupe(issues: List[SpecIssue]) -> List[SpecIssue]:
    seen = set()
    out = []
    for issue in issues:
        key = (tuple(issue.path), issue.message)
        if key not in seen:
            seen.add(key)
            out.append(issue)
    return out


def parse_spec(data: Any) -> Tuple[VideoSpec | None, List[SpecIssue]]:
    """Migrate and validate. Exactly one of the two results is set."""
    try:
        migrated = migrate(data)
    except SpecVersionError as exc:
        return None, [SpecIssue(path=["spec_version"], message=str(exc))]
    try:
        return VideoSpec.model_validate(migrated), []
    except ValidationError as exc:
        issues = []
        for err in exc.errors(include_url=False):
            message = err["msg"]
            # "Value error, x" is Pydantic telling us a validator raised ValueError,
            # which is every structural rule; the prefix means nothing to a person.
            if message.startswith("Value error, "):
                message = message[len("Value error, "):]
            issues.append(SpecIssue(path=_clean_path(tuple(err["loc"])), message=message))
        return None, _dedupe(issues)
