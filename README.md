# Gecko Video Creator (GVC)

One place to put narrated video presentations together quickly, scene by scene. Part
of the Gecko Suite, alongside [Gecko Notes](https://github.com/davior/gecko-notes)
(scripts, and the suite's sign-in) and [GAM](https://github.com/davior/gam) (the media
library).

A video is a JSON document, the **VideoSpec**. It holds:
- the scenes and the narration read over each one;
- titles and on-screen text;
- clips cut out of GAM footage;
- any number of soundtracks, starting and stopping at chosen scenes;
- a default transition, which any scene can override;
- per-scene Ken Burns moves, down to which part of a picture the camera drifts over.

There are three ways to start one:
- **by hand**, scene by scene;
- **from a prompt**, where an AI drafts the whole spec and you tweak it;
- **pushed from a note** in Gecko Notes, after which the project lives in GVC.

## Status

**M2 (the renderer).** Build a video by hand, or push one in from Notes. Find footage in
GAM by what is said in it. Then preview and render it:
- per-scene transitions and Ken Burns moves between two frames of a picture;
- any number of soundtrack tracks, crossfading between scenes;
- trimmed clips, and narration read through Gecko Notes;
- text, lower thirds and pictures on screen, timed to the scenes and lines they belong to;
- end credits from the library's attribution, and a description with chapters and credits.

A finished render can be saved back into GAM. AI drafting and the full storyboard
editor are next (M3, M4).

## Read first

- [`docs/plan-of-attack.md`](docs/plan-of-attack.md): where things stand, the decisions
  taken and the milestone order.
- [gecko-notes `docs/gecko-video-creator.md`](https://github.com/davior/gecko-notes/blob/main/docs/gecko-video-creator.md):
  the VideoSpec's design, with a full worked example.

## Development

See [`CLAUDE.md`](CLAUDE.md) for ports, the Python version and the commands to run.
