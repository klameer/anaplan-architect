# Hosting

## What it does

One process, one SQLite file, one folder of uploaded files. It runs on a laptop, on a server inside an
organisation, or on a host such as Railway, from the same code.

## Three ways to run it

**1. Docker, on your own machine**

```bash
docker compose up
```

Opens at `http://localhost:8765`. The port is published to your machine only, so there is no login. The two demo
workspaces are written on first start. Put your model key in `.env` first.

**2. Python**

```bash
python -m venv .venv
.venv/bin/pip install ".[llm,web,openai]"        # Windows: .venv\Scripts\pip
.venv/bin/anaplan-architect demo --data ./data   # optional: the demo workspaces
.venv/bin/anaplan-architect serve --data ./data
```

The install fetches two libraries from GitHub, so `git` must be on the path.

**3. A server for several people**

Run the image with a volume on `/data`, publish the port, and set:

```bash
ARCHITECT_ADMIN_USER=you
ARCHITECT_ADMIN_PASSWORD=at-least-ten-characters
ARCHITECT_HOSTED=1
```

The admin is created once, on first start. The admin creates every other login from the admin panel.

## Settings

| Variable | What it does |
|---|---|
| `ARCHITECT_ADMIN_USER`, `ARCHITECT_ADMIN_PASSWORD` | Create the admin on first start, while there are no logins |
| `ARCHITECT_HOSTED=1` | Behind a proxy that ends TLS: Secure cookies, HSTS, the forwarded address believed, API docs off |
| `ARCHITECT_OPEN=1` | No login at all. Only for a container whose port is published to localhost |
| `ARCHITECT_DEMO=1` | Write the demo workspaces on first start |
| `ARCHITECT_NOTICE` | The notice shown on the sign-in page |
| `ARCHITECT_DEFAULT_CAP_USD` | The spend cap a new login starts with (default 2.00) |
| `ARCHITECT_MAX_UPLOAD_MB` | The most one request may carry (default 200) |
| `ARCHITECT_CONTEXT_BUDGET` | Tokens of context for one answer (default 32,000) |
| `ARCHITECT_MAX_CHATS_PER_LOGIN` | Answers one login may have in flight at once (default 2) |
| `ARCHITECT_MAX_CHATS` | Answers in flight on the whole instance (default 16) |
| `ARCHITECT_MAX_EXPORT_READS` | Sets of exports read at once (default 2); `ARCHITECT_EXPORT_WAIT_S` is how long an upload waits for a turn (default 20) |
| `ARCHITECT_THREADS` | Worker threads (default 64) |

Model settings are on [Model providers](model-providers.md); tracing on [Tracing](tracing.md).

## On Railway

`railway.json` builds the `Dockerfile` and sets the health check, one replica. A volume cannot be declared in that
file: attach one to the service in the Railway project. The image keeps the store wherever Railway mounts it.
Without a volume the store is lost on every deploy. Set the three variables above.

## A login on the hosted test instance

Karim runs a hosted test instance. A login on it is by request and at his discretion: not everyone who asks gets
one, access can be withdrawn at any time, and the instance may be reset. To ask, send him a message on
[LinkedIn](https://linkedin.com/in/karimlameer). That is the only route: not through the website and not by email.
Do not upload anything you are not allowed to share.

## How many people at once

One instance is sized for about eight people working at the same time, with 1 GB of memory (2 GB if the models are
large). Each has their own workspaces; they can upload, ask and browse at once.

That figure is measured, not estimated. `python tools/load_check.py` starts a real server with a made-up model
behind it and has eight logins, two workspaces each, work at once for three minutes: uploading exports and
documents, asking questions that call tools, switching workspace, taking backups, deleting chats and workspaces.
On the author's laptop (2026-11-14): 3,787 requests, 838 questions answered, no errors, nothing from one workspace
in another's answers, one spend-ledger row per model call. Sign-in took under a second throughout (95th percentile
0.5 s; 0.07 s while all eight had a question in flight). The server held 674 MB at its peak, after four logins sent
a 43 MB export each at the same moment. The process that reads exports is separate and adds its own memory while it
runs. A shorter form of the same check runs with the tests.

What a person sees at the limit is a sentence, not an error:

- A third question while two of yours are being answered: *You already have 2 questions being answered. Wait for
  one to finish, then ask again.*
- Sixteen answers in flight on the instance: *The instance is answering 16 questions at once, which is its limit.
  Wait a moment and ask again.*
- Exports are read two sets at a time. An upload waits up to twenty seconds for its turn, then: *The instance is
  reading other people's exports right now. Nothing of yours was kept: give it a minute and try again.*
- The model provider's own rate limit: *The model provider is turning requests away for the moment: its rate limit,
  not this instance's and not yours. Wait a minute and try again.*

The store is one SQLite file in WAL mode: reading never waits for writing, and writes queue behind each other for
up to thirty seconds. More people than this is a bigger machine, not more replicas.

## Limits to know

- One instance only: the store is a single SQLite file.
- Nothing is encrypted at rest. Whoever has the volume reads everything.
- The image has been built and run from the public repository (2026-11-14): on your own machine it is healthy in about six seconds with both demo workspaces, runs as a non-root user and holds about 86 MB at rest; in hosted mode with a volume, sign-in, Secure cookies, the security headers and a restart that keeps logins and sessions were checked. Not yet tried: a question with a real model key inside the container, and `docker compose up` itself (the image was started with `docker run`).

Read [what it protects and what it does not](../SECURITY.md) before putting it in front of other people.

## How it is built

`create_app` and `serve` in `src/anaplan_architect/web.py`; the console in `src/anaplan_architect/cli.py`
(`serve`, `demo`, `users`, `backup`, `restore`); `Dockerfile`, `docker-compose.yml`, `railway.json`,
`constraints.txt`. Tests: `tests/test_hosting.py`.
