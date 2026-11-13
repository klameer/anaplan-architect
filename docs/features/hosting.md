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

## Limits to know

- One instance only: the store is a single SQLite file.
- Nothing is encrypted at rest. Whoever has the volume reads everything.
- The Docker image is written and has not yet been built and run by its author; the Python route is the one that
  has been followed from a clean machine.

Read [what it protects and what it does not](../SECURITY.md) before putting it in front of other people.

## How it is built

`create_app` and `serve` in `src/anaplan_architect/web.py`; the console in `src/anaplan_architect/cli.py`
(`serve`, `demo`, `users`, `backup`, `restore`); `Dockerfile`, `docker-compose.yml`, `railway.json`,
`constraints.txt`. Tests: `tests/test_hosting.py`.
