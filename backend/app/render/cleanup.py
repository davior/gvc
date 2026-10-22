"""Remove render rows whose video is gone.

Until `DATA_DIR` was set in the image, renders were written to `/data`, outside the
volume, so every rebuild deleted the files and kept the rows: a project's render list
then offered videos that 404 on play, and "Save to GAM" refused them. This finds those
rows and, with `--apply`, deletes them.

    docker compose exec gvc-backend python -m app.render.cleanup            # list only
    docker compose exec gvc-backend python -m app.render.cleanup --apply    # delete

Listing is the default because deleting is not undoable, and a mistyped data directory
would make every render look orphaned: run it once to see that the count is the one
you expect. A render's row is the only thing deleted. A copy already saved to GAM lives
there independently and stays.

Only finished renders are judged. A failed or cancelled one never had a file, and a
running one is still writing it.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from sqlmodel import Session, select

from app.models.render import RenderJob
from app.render import worker


@dataclass
class Orphans:
    rows: List[RenderJob] = field(default_factory=list)
    kept: int = 0


def find(session: Session) -> Orphans:
    found = Orphans()
    for job in session.exec(select(RenderJob).where(RenderJob.status == "done")).all():
        path = worker.renders_dir() / job.id / (job.video_path or "")
        if job.video_path and path.is_file():
            found.kept += 1
        else:
            found.rows.append(job)
    return found


def remove(session: Session, rows: List[RenderJob]) -> None:
    for job in rows:
        # A poster or subtitle can outlive the video it went with.
        shutil.rmtree(worker.renders_dir() / job.id, ignore_errors=True)
        session.delete(job)
    session.commit()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.render.cleanup",
                                     description="Remove render rows whose video is gone.")
    parser.add_argument("--apply", action="store_true",
                        help="delete them (without it, only list them)")
    args = parser.parse_args(argv)

    from app.database import engine

    with Session(engine) as session:
        found = find(session)
        print(f"Renders directory: {worker.renders_dir()}")
        print(f"{found.kept} finished render(s) have their video; "
              f"{len(found.rows)} do not.")
        for job in found.rows:
            saved = f", saved to GAM as {job.gam_asset_id}" if job.gam_asset_id else ""
            print(f"  {job.id}  project {job.project_id} v{job.version_seq}  "
                  f"{'preview' if job.preview else 'full'}  {job.created_at:%Y-%m-%d %H:%M}{saved}")
        if not found.rows:
            return 0
        if found.kept == 0 and not args.apply:
            print("\nNo render has its video. If that's unexpected, check the renders "
                  "directory above before applying.")
        if not args.apply:
            print("\nNothing deleted. Run again with --apply to delete these rows.")
            return 0
        remove(session, found.rows)
        print(f"\nDeleted {len(found.rows)} row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
