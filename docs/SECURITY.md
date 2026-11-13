# Security: what this protects, and what it does not

Rewritten 2026-11-13 after an independent code review and an independent security review of commit `408cf35`, to
describe the code as it is after their findings were fixed. Report a problem privately to the maintainer before
opening a public issue.

## What it is

One process (FastAPI), one SQLite file, one folder of uploaded files. No other service. It is built for one person
on their own machine, or a small trusted group on a test instance. It is not built for strangers with valuable data.

## Who can reach what

| Run as | Who gets in |
|---|---|
| Bound to localhost, no logins created | Anyone who can open a port on that machine. No login. |
| Container with `ARCHITECT_OPEN=1` | The same: open. Only safe while the port is published to localhost. Publish it to a network with this set and everyone on that network is in. |
| Bound to a network, no logins | Nothing is served except how to create the admin. |
| Any, once a login exists | Signed-in logins only. There is no signup; the admin creates every login. |

The admin is created from the console, or on first start from `ARCHITECT_ADMIN_USER` and `ARCHITECT_ADMIN_PASSWORD`.
Those two variables stay in the host's environment afterwards.

Before signing in, a caller gets the notice, whether logins exist, and nothing about the server: not its data folder,
its bind address, the model provider, the model, the endpoint or a tracer's error. The data folder and the bind
address are shown to the admin only.

## Hosted mode

Set `ARCHITECT_HOSTED=1` on any instance that sits behind a proxy ending TLS (Railway, a company gateway). The app
itself then sees plain http, so without the switch it cannot know the outside is https. With it:

- the session and CSRF cookies are always `Secure`;
- `Strict-Transport-Security` is sent on every response;
- the forwarded scheme and client address are believed (the sign-in throttle needs the real address). Only set the
  switch where a proxy you trust is the only way in: with it, anyone who can reach the app directly can claim any
  address;
- the API's own documentation pages (`/docs`, `/redoc`, `/openapi.json`) are off.

## Workspace isolation is in name only

Every workspace lives in the same SQLite file and the same blob folder. Isolation is a membership row per workspace
and login, checked in one middleware before any handler runs: a path that names a workspace, or a chat, upload,
model, note, document, answer or citation inside one, is answered only to a member, and with 404 to anyone else.
The chat tools take their workspace from the conversation, not from the model.

What holds it together, beyond that check:

- **A snapshot is read only through its own workspace.** The function that opens a workspace refuses a snapshot that
  belongs to another one, and a citation that points at another workspace's snapshot opens nothing.
- **A restore cannot plant rows that reach elsewhere.** A backup is a file its owner can edit. It is refused whole
  unless it is closed over itself: exactly one workspace row, the manifest's; every other row pointing only at that
  workspace and at rows the same archive carries; no id already held in the store.
- **A note cannot borrow from another workspace.** Its sources resolve only to citations its own workspace holds, and
  its model must be a model of its workspace. An id from elsewhere looks the same as one that does not exist.
- **Asking whether a login is a member never writes.** Workspaces made while a store ran with no logins go to the
  first admin when that admin is created, once. A store upgraded from v0.1 keeps every login in every workspace.
- **Ids are not guessable.** New ids carry 64 random bits after the date. Ids made before 2026-11-13 carry 16 and
  still resolve; they appear in addresses and chat exports, so treat an old workspace's ids as known to its members.

What it still means:

- Anyone with the data folder, the volume, or a backup reads every workspace. Nothing is encrypted at rest.
- Whoever runs the host reads everything. The admin panel shows, for each login, usage figures (sign-ins, counts of
  workspaces, uploads, documents and questions, spend) and, for each workspace, its name, members and counts. The
  sign-in notice says so. Nothing inside a workspace opens for the admin, but that is the page, not a control.
- The admin can delete any workspace (name typed back). That is the one request on someone else's workspace the
  membership check lets through.
- A route whose path does not follow the `/api/<family>/<id>` shape would not be covered by the one check. A test
  walks every route as a non-member and fails on a route it does not recognise.
- Restoring or inspecting a backup that claims an id already in the store says the id is taken. It never says whose
  workspace it is or what it is called, but it does confirm that the id exists.

## What leaves the machine

- **To the model provider**, when a question is asked or a document is uploaded: the question, a summary of the
  workspace (model, module and line item names, formulas, sizes), owner notes, document cards, and whatever sections
  and tool results the answer pulls. Settings names the provider and endpoint. The provider's data policy applies.
- **To LangSmith**, only if `LANGSMITH_API_KEY` is set, and then only what each login's own level allows. The level
  is read for every question, from whoever asked it:
  - **Off**: nothing is sent for that login's questions or for the summaries of documents it uploads. This is the
    default for every login that is not the admin's.
  - **Structure**: each turn as a run tree with the tool names and their order, sizes, tokens, cost, timings, the
    model's name, ids and the verdict's counts. Questions, answers, tool arguments and results, document text, object
    names, the chat's title and error text are replaced by their sizes. A dict key is kept only when it is a field name
    the code knows; any other key is numbered, because it could be an object's name.
  - **Full**: all of that plus the content. Email addresses and strings shaped like API keys are replaced first, by
    pattern; other personal data is not. This is the default for the admin's own questions, and for a store with no
    logins, where the person asking is the person who set the key.
  A login that is not the admin's changes its own level in its own Settings, after being told that whoever runs the
  instance will be able to read what it sends and that it also sits with LangSmith; the choice is stored with its
  time. Turning it off stops anything further; what was sent is not deleted. Nobody sets another login's level: the
  admin's API refuses it and the admin panel only shows it. `LANGSMITH_TRACE_CONTENT=0` is a ceiling for the whole
  instance: nobody above Structure. What this does not do: it does not stop an admin reading the data folder, and a
  login's earlier traces stay in LangSmith until someone deletes them there.
- **To Google Fonts**, from each browser that opens the app: a request for the two typefaces (the browser's address
  and user agent, no content).
- **Nothing else.** No telemetry, no update check. Scripts are served by the app itself.
- The Codex route sends the same content to ChatGPT's backend over an undocumented interface, on the ChatGPT
  subscription of whoever ran `codex login` on the server. On a shared instance every login's questions spend it.

## What the browser may load

Every response carries a Content-Security-Policy: the app's own files, inline styles, and the two font hosts. No
image, script, frame or request to any other origin. Answers, notes and document passages are also sanitised before
they are shown: images, media, frames, forms and styles are dropped, links are kept. Both are there for one reason:
text the model wrote may have been steered by text it read, and an image address is a way to carry data out.
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and frame denial are set too. The standalone estate
report is one self-contained page with its own inline script, so it carries a policy of its own: that script and its
styles run, and the page can reach nothing at all, the app included. A real browser is
asked both questions by `tools/ui_check.py`.

## Text the model reads, and what the model can write

Uploaded text is model input. A document, an export's notes column or a formula can contain instructions aimed at the
model. The instructions it runs under say that such text is material to report, never an instruction, and that it
must not write images or links the owner did not give; that is a request to a model, not a guarantee.

The model has **five tools that write**, all inside the workspace of the conversation:

| Tool | What it writes |
|---|---|
| `remember` | a note, kept as the assistant's working assumption |
| `set_status` | the review state of a pattern, with a reason |
| `set_edge_state` | a feed between two models as confirmed or retired, with a reason |
| `propose_action` | a card on the improvement plan, marked as a proposal |
| `set_action_state` | the state of a card on the improvement plan |

None of them sends anything outside the workspace or deletes anything. But a hostile document can get the model to
call them. What limits the damage:

- A note the assistant keeps is never the owner's word: it is stored as a working assumption with its origin, shown
  on the Notes page as kept by the architect, and reaches later prompts labelled "kept by the assistant, not confirmed
  by the owner". When the chat had read project documents, the note's title says so.
- The validator checks names, figures and quotes against the estate and the documents. It does not detect
  manipulation. The other four writes carry a reason and who made them, and are visible on the pages they change.
- So the worst case is a wrong or misleading answer, note, status or card inside that one workspace, which its
  members can see and undo. Nothing leaves, and nothing in another workspace changes.

## Uploads

- Model exports (CSV) and project documents (PDF, Word, Markdown, text, CSV). An export file is stored under the
  hash of its bytes. A document's file is not kept: its text is, split into sections. The name a user gives a file is
  kept as text and never used as a path.
- **Sizes.** No request may carry more than `ARCHITECT_MAX_UPLOAD_MB` (default 200), refused by its declared length
  before it is read; a body sent in chunks with no declared length is refused. Documents: 20 per workspace, 10 MB each, refused by
  the upload's declared size before it is read; replacing a document that is not there does not get round the count.
  A Word file whose text would unzip to more than 40 MB is refused by the size the zip declares, and the read stops
  there whatever was declared. A backup's tables are held to 64 MB each and the archive to 4 GB unzipped, checked
  before anything is unzipped.
- PDF text is read with pypdf, in the server process, not sandboxed. A test feeds it truncated, self-referencing and
  junk files and checks each is refused with a reason. That is a handful of cases, not a hardening: a PDF built to
  make pypdf spend minutes or gigabytes has not been tried.
- A question may be up to 8,000 characters.
- Nothing uploaded is executed.

## Sessions, sign-in and CSRF

- Passwords: scrypt (n=2^14, r=8, p=1), a salt per password, ten characters minimum. A generated password is shown
  once to the admin.
- Sign-in is slowed: five failures for a name, or twenty from one address, inside fifteen minutes, and sign-in for
  that name or address is refused without the password being looked at, until the oldest failure is fifteen minutes
  old. The count is kept in SQLite, so a restart does not clear it. A name that exists and one that does not cost the
  same: one password hash. A side effect to know: anyone can keep a known username locked out by failing on purpose.
- Session: a random token in an HttpOnly, SameSite=Lax cookie, stored as its SHA-256, 30 days. `Secure` when the
  request arrived as https or the instance is in hosted mode.
- CSRF: every changing request from a signed-in login must carry a header equal to a second cookie.
- A password reset or a disable signs that login out everywhere.
- **Not there**: no two-factor; no forced password change after a reset. An open (no-login) instance has no CSRF
  check at all.

## Spend cap

Each login has a cap in US dollars, counted at list price whatever the route bills. What a login has spent is a
ledger of its own: one row per model call, written when the call returns. Deleting a chat or a workspace takes
nothing off it, and a turn that fails, is abandoned or stops at the tool-call limit has still spent what its calls
cost. The cap is checked before every model call, not once per question, so a long turn stops when the cap is
reached; the summary written when a document is uploaded is checked and counted the same way. Calls already in
flight when the cap is reached finish, so several chats asked at once can overshoot by those calls, and a call that
errors before it returns its usage is not counted. The admin has no cap unless one is set. It is a budget guard, not
a rate limit.

## Secrets

Keys are read from the environment or `.env`, which is ignored by git and by the Docker build. They are not written
to the store, to backups or to traces. A backup zip holds a workspace's content and no credentials: its models and
export files, its project documents (their text by section and the objects each section names), notes, chats with
their citations, and decisions. The Codex route's tokens stay in the file `codex login` wrote, readable by whoever
can read the server's home folder.

## Publishing

`tools/make_public.py` writes the public repository as an export: one commit, no history, no remote. It is committed
under the publisher's CodelessOps address, set in the tool, whatever git is configured with on the machine; that
address is allowed in the commit's metadata only, as that exact address. Every file is scanned for private words,
anything shaped like a key, and email addresses; files that are not text are scanned as bytes and named in the
report; the commit's own author, committer and message are scanned by the same rules. The two libraries it is built
on are pinned to commits, not tags, in `pyproject.toml`, `pins.json` and the `Dockerfile`, and the image installs
everything else with `constraints.txt`. The base image (`python:3.12-slim`) is a tag, not a digest.

## Known limits, in one place

1. One file, one process, no encryption at rest: isolation depends on one check, with one exception (the admin's delete).
2. Document and PDF parsing is not sandboxed; hostile PDFs are only lightly tested.
3. Document text can steer the model's answer and its five writes inside the workspace.
4. Open mode trusts everyone who can reach the port; hosted mode trusts the proxy in front of it.
5. A known username can be locked out by someone failing on purpose.
6. A quoted word or two, or a single-quoted or italic phrase, that is not in the section word for word is shown as
   not checked: it is neither verified nor flagged.
7. The Docker image has never been built or run: it is written and its install steps were followed by hand in a
   clean environment. `constraints.txt` was taken from a Windows install and has not been resolved on Linux.
8. Not looked at by either review: `codex.py`, `openai_compat.py`, `cli.py`. The builder read them for shell calls,
   disabled certificate checks and secrets in messages, found one (a token service's reply repeated in an error) and
   fixed it. That is a read by the author, not a review.

### Accepted for a test instance

Karim accepted these seven on 2026-11-13, for a test instance whose logins are handed out by him. They are limits
that stay, not work in progress:

1. **Spend cap overshoot.** Chats asked at the same moment can pass the cap by the calls already in flight, and a call
   that errors before it returns its usage is not counted.
2. **Sign-in lockout abuse.** Anyone can keep a known username locked out by failing on purpose.
3. **Four write tools documented only.** `set_status`, `set_edge_state`, `propose_action` and `set_action_state` can be
   called by a model steered by a hostile document; only `remember` marks where its note came from.
4. **Old short workspace ids.** Ids made before 2026-11-13 carry 16 random bits and still resolve.
5. **Pins for the image.** `constraints.txt` was resolved on Windows, not Linux, and the base image is named by tag,
   not by digest.
6. **Hostile-PDF coverage.** Six malformed files are tested; a PDF built to exhaust the parser has not been tried.
7. **`codex.py`, `openai_compat.py`, `cli.py`.** Read by their author only, not reviewed.

**Still open, not accepted:** the Docker image has never been built or run. Building it and passing the demo script in
it is a step before any Railway deploy.
