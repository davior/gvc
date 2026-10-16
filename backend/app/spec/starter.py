"""What a project made by hand starts as.

A title card and one empty scene, rather than nothing: an empty segment list renders
nothing and gives the editor nothing to click on, and almost every video opens with a
title. The project-wide defaults are set explicitly, not left to the model's, because
they are the first thing someone building by hand will want to change, and a default
that isn't in the document is a default nobody can see.
"""

from app.spec.model import VideoSpec


def starter_spec(title: str) -> VideoSpec:
    title = title.strip() or "Untitled video"
    return VideoSpec.model_validate({
        "title": title,
        "style": {
            # A short fade between scenes. Notes' default is a hard cut, but a video put
            # together scene by scene almost always wants something softer, and per
            # scene it is one click to override.
            "transition": {"style": "fade", "duration": 0.6},
            "motion": {"effect": "alternate", "amount": 0.12},
        },
        "segments": [
            {
                "id": "s_title",
                "kind": "card",
                "role": "title",
                "label": "Title",
                "card": {"variant": "title", "title": title},
            },
            {
                "id": "s_1",
                "kind": "scene",
                "label": "Scene 1",
                "narration": {"beats": [{"id": "b1", "text": ""}]},
            },
        ],
    })
