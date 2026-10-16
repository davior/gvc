# gvc — Claude Instructions

Gecko Video Creator. Part of the Gecko Suite alongside
[gecko-notes](https://github.com/davior/gecko-notes) (scripts, and the identity provider)
and [gam](https://github.com/davior/gam) (the media library).

Read [`docs/plan-of-attack.md`](docs/plan-of-attack.md) before starting a milestone. It
records where things stand, the milestone order and the reasoning behind decisions that
would otherwise look arbitrary.

## The VideoSpec

A video is one JSON document. Its design, with a full worked example, is gecko-notes'
[`docs/gecko-video-creator.md`](https://github.com/davior/gecko-notes/blob/main/docs/gecko-video-creator.md)
("the Notes spec doc"). Read §4–§6 there before touching `backend/app/spec/`. GVC's
copy of the model (`backend/app/spec/model.py`) is canonical from M0 on. It carries
the changes this repository's plan lists as S1–S3, which Notes' copy does not.

## GVC stands by itself

- A video can be made entirely by hand. Never make a feature depend on a note or on
  the AI being there.
- A note pushed in from Notes becomes an ordinary GVC project. Nothing re-reads the
  note afterwards, and `source` is provenance only.
- The one runtime dependency on Notes is login: GVC verifies the JWT Notes issues and
  has no accounts of its own.

Changes GVC needs from GAM or from Notes are specified in the plan ("Changes needed
in GAM / in Notes"). Don't apply them from here, since those are separate repositories.
When you need to know how either of them does something, **read its source, not its
README**.

GVC mirrors GAM's skeleton (config, auth, Alembic, CI), and GAM is the place to look
first for a pattern. GAM's `CLAUDE.md` explains why each convention below exists.

## Code conventions

**API contract**
- Single resources: `{"data": T}`. Lists: `{"data": [T], "total", "limit", "offset"}`.
- Errors: `{"detail": {"code": "snake_case_code", "message": "human sentence"}}`.

**Backend**
- All environment configuration goes through `app/config.py`. Never `os.getenv` at
  module scope.
- Schema changes are Alembic migrations. Never a `try: ALTER TABLE …; except: pass`.
- Get the caller with the `CurrentUser` dependency.
- Structured data is JSON-as-TEXT in a `str` column, decoded on read. A VideoSpec is
  stored that way and validated by the Pydantic model on every write.
- Primary keys are `str(uuid.uuid4())` generated at the call site.
- Timestamps are naive UTC, named `created_at` / `updated_at`, and come from
  `app.clock.utcnow`: never `datetime.utcnow()`, never `datetime.now(UTC)`.
- Tests go through `TestClient` against real routes.

**Frontend**
- Types live beside the api module that owns them. There is no `types/` directory.
- One `xApi = { … }` object per backend router, in `src/api/`, over the shared axios
  client.
- Zustand stores without middleware. Guard every await with a staleness check before
  `set(...)`, expose `reset()`, and fan it out on logout.
- Imports use the `@/` alias. No barrel `index.ts` files.
- 2-space indent, single quotes, no semicolons, enforced by Prettier.

**Comments** explain *why*, not *what*. A comment that records a constraint, a rejected
alternative or a load-bearing subtlety is the most valuable thing in the file.

## After every change (dev environment)

Dev ports are **8002 and 5175**. Notes uses 8000/5173 and GAM 8001/5174, and all three
run at once. `vite.config.ts`'s proxy target has to match the port uvicorn is started
on, or the frontend reaches a sibling's backend. That backend shares `JWT_SECRET_KEY`,
so it answers instead of erroring.

The backend runs on **Python 3.13**, pinned by `.python-version` and matched by
`backend/Dockerfile` and CI. Build the venv with `uv venv` or `python3.13 -m venv`,
never a bare `python3`.

Migrations don't run on startup. `alembic upgrade head` lives in
`backend/entrypoint.sh`, and nothing runs it for a bare `uvicorn`.

```bash
# Backend — http://localhost:8002
cd backend
alembic upgrade head
uvicorn app.main:app --reload --port 8002

# Frontend — http://localhost:5175 (proxies /api to :8002)
cd frontend && npm run dev
```

For local use without Notes running, set `ENVIRONMENT=development` and
`DEV_AUTH_USER=<any id>` in `.env`.

Under Docker the frontend is a compiled bundle served by Nginx:
`docker compose up --build -d`, then hard-refresh.

## Before pushing

```bash
cd backend && pytest -q
cd frontend && npm test && npm run build    # build also typechecks
```

## After committing to a non-main branch

Report the pull request for that branch: number, URL, title, draft and CI status. If
none exists, open a **draft** PR and report it.

## After every commit to main (production deployment)

```bash
git pull origin main
docker compose up --build -d
docker compose ps
curl -f http://localhost:${APP_PORT}/api/health
```

- `data/db/` is bind-mounted, so it survives rebuilds.
- `JWT_SECRET_KEY` must be set and must **match gecko-notes'**. The app refuses to
  start without it.
- Behind the reverse proxy, set `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`
  in `.env` so the frontend joins the external `web` network.
