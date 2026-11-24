# Security: what this protects, and what it does not

Rewritten 2026-11-13 after an independent code review and an independent security review of commit `408cf35`, to
describe the code as it is after their findings were fixed. How to report a problem is in
[SECURITY.md](../SECURITY.md). Which commit each review was run on, what it found and what was fixed is in
[the review log](SECURITY-REVIEWS.md): this page describes the design, the log says which version was reviewed.

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

Every workspace lives in the same SQLite file and the same blob folder. Isolation is one membership check, made in
one middleware before any handler runs. A Private workspace is its member row's (the login that made or restored it).
A Shared workspace belongs to the team it is shared with: a login is a member while it is in that team, at the moment
of asking, and only then, its maker included. An admin is in no team. With that check: a path that names a workspace, or a chat, upload,
model, note, document, answer or citation inside one, is answered only to a member, and with 404 to anyone else.
The chat tools take their workspace from the conversation, not from the model.

What holds it together, beyond that check:

- **A snapshot is read only through its own workspace.** The function that opens a workspace refuses a snapshot that
  belongs to another one, and a citation that points at another workspace's snapshot opens nothing.
- **A restore cannot plant rows that reach elsewhere.** A backup is a file its owner can edit. It is refused whole
  unless it is closed over itself: exactly one workspace row, the manifest's; every other row pointing only at that
  workspace and at rows the same archive carries.
- **A restore brings no id of its own.** Every id in an archive (the workspace's, and each upload's, chat's, answer's,
  note's, document's, section's, proposal's and citation's) is replaced by one this server makes, in the rows and in
  the text of the answers. Nothing in an archive can collide with the store, so a restore cannot be used to ask
  whether an id exists, to take over an id, or to make someone else's backup unrestorable. Ids must be in the shape
  the server makes before they are replaced, so one cannot be an ordinary word of an answer. Everything restored is
  authored by the restorer; the archive's authors are kept as text only.
- **A restored copy of a shared workspace is not shared on.** A backup says whether it held anything another login
  added. A copy restored from one that did comes back Private and cannot be shared with a team until the admin
  allows it, because every row in it is the restorer's now and nothing else would say whose it was. This limits
  re-sharing inside the instance by the honest route. It does not limit copying: a maker can always take out what
  they could already read, and the fact is a line in a file they can edit.
- **A citation id is answered from one workspace.** An id is a hash of what it cites, not of whose it is. It is
  resolved inside the workspace the membership check chose for the asker, and "cited in" lists that workspace only.
- **A note cannot borrow from another workspace.** Its sources resolve only to citations its own workspace holds, and
  its model must be a model of its workspace. An id from elsewhere looks the same as one that does not exist.
- **A team is a company, and Shared stops at it.** A workspace is Private or Shared with one team, the team its maker
  was in when it was shared. There is no setting that opens a workspace to every login on the instance. A team's
  access is never written as membership rows: it is read from the login's current team each time, so a login moved
  out of a team, or disabled, is out at once.
- **A shared workspace belongs to its team, not to its maker.** A maker moved out of the team loses it like anyone
  else; it stays with the team and has no maker until the admin names a team-mate. A workspace is shared only with
  the team it was last shared with, or with a team every one of its authors is in now: a team-mate's content never
  follows the maker to another company.
- **Only the maker shares; the maker or the admin makes private or deletes.** The admin does it from the admin panel,
  on a route outside the workspace's own, so the one check is not widened for it. The admin cannot share a
  workspace, cannot be put in a team, and a login in a team cannot be made an admin.
- **A team-mate adds; they change or remove only what they added.** Renaming, archiving and taking a backup of a
  shared workspace are its maker's.
- **A backup is not a way round.** It carries no team, and a restore comes back Private to the login that restored it.
- **Who asked is given with the question.** The asker's name, cap, ledger and tracing level go to the chat with their
  question, by the request that holds the chat's lock. A request that finds the chat busy changes nothing. Every
  model call checks first that the asker is still in the workspace; an answer under way when they lose it stops, and
  is neither shown nor kept.
- **Nothing says whether an id exists.** An id that is not yours and an id that is not in the store get the same
  404, with the same words, on every route. A backup naming someone's workspace id is told nothing. `/health` gives
  the number of workspaces only to someone signed in.
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
- **Sharing widens who can read a workspace, on purpose.** In a shared workspace every member reads every chat,
  note and document in it, including ones written before it was shared and ones a colleague would have thought of
  as their own. The page says so above the chat box, and the share dialog says so before the maker confirms, but it
  is a statement on a page, not a control. A team-mate cannot download the workspace as one file, but can read
  and copy everything in it.
- **A team is whatever the admin picks.** A team is made once, by name, and picked from a list for each login. Names
  are compared without case, width, spacing or invisible characters, and a name mixing alphabets is refused, so a
  look-alike does not make a second company by accident; a name written wholly in another alphabet still can. A login
  put in the wrong team sees that team's shared workspaces. Nothing checks a login's company but the admin.
- **A workspace with no maker waits for the admin.** Until the admin names one, nobody can rename it, back it up or
  make it private; the team keeps reading and adding to it.
- A route whose path does not follow the `/api/<family>/<id>` shape would not be covered by the one check. A test
  walks every route as a non-member and fails on a route it does not recognise.
- **What reaches the tracer under one login's consent.** A login that turns content tracing on sends its own
  questions and what the tools pulled to answer them: text of the workspace's documents and notes, whoever added
  them, and its object names. That is the workspace's content going out on one member's choice, and the Settings
  page says so. What does not go on someone else's choice: another member's question (sent as its size only), and a
  chat's title, which is the first question of whoever started the chat: the trace's root run is named
  "conversation", never by the title.
- **Tracing in a shared chat.** A turn records what its asker let the tracer have. When a later asker in the same
  chat has content tracing on, earlier turns asked by someone who had not go as their size only. Turns from before
  2026-11-24 carry no record and are treated as not agreed.

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
    pattern; other personal data is not. This is the default for the questions of the one login the instance was
    set up with (who also set the key), and for a store with no logins, where the person asking is the person who
    set the key. A login made an admin later did not choose that: it sends nothing until it turns tracing on itself.
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
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and frame denial are set too. A real browser is
asked both questions by `tools/ui_check.py`.

**A link in an answer stays a link.** A document can steer the model into writing one. It is shown with the site it
goes to written beside it, opens in a tab of its own, and carries `rel="noopener noreferrer nofollow"`. The editing
pass cannot add one: an edit with a link or an address the draft did not have is thrown away. A link the model wrote
in its own draft is still shown, marked that way: that is a label, not a block.

**The estate report page** is written by the anaplan-estate library from names in the exports, on one self-contained
page with one inline script. Until 2026-11-24 a module or line item named like a markdown link could close the link's
address and add attributes of its own, and the page's policy let inline script run. Now the page is read tag by tag
before it is served (`reportpage.safe`: no event handler, no link that leaves the page, no style on a link or one
that positions or fetches), and its policy allows the library's one script by its hash and nothing else, with no
`'unsafe-inline'` for script, in a sandbox with no origin: a script that ran there could not read the app's cookie or
call the app as the reader. The library's own fix (escape quotes in `htmlout._inline`) is not yet in the pinned
version; the two locks above do not depend on it.

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
  junk files and checks each is refused with a reason. A PDF may have up to 2,000 pages and its reading is stopped
  after 60 seconds, checked between pages. That is a handful of cases and two limits, not a hardening: one page built
  to make pypdf spend minutes or gigabytes is not stopped by a check made between pages, and has not been tried.
- A Word file is read as it streams, a paragraph at a time, with a limit on paragraphs (60,000) and on structure: a
  file of a hundred kilobytes that unzips to 40 MB used to take over 500 MB of memory to read.
- Reading documents and restoring a backup are gated like reading exports: a few at once on the instance, one of each
  kind per login. A login's export files have a ceiling on the volume (`ARCHITECT_MAX_STORAGE_MB_PER_LOGIN`, 2,000 MB).
- Linking a document's sections to the model's objects is done before the store is written, so a long document in a
  large model does not hold the one write lock.
- A question may be up to 8,000 characters.
- Nothing uploaded is executed.

## Sessions, sign-in and CSRF

- Passwords: scrypt (n=2^14, r=8, p=1), a salt per password, ten characters minimum. A generated password is shown
  once to the admin.
- Sign-in is limited, and nothing waits on the server for it: a try over a limit is answered 429 at once, with how long
  to wait. The count is kept in SQLite, so a restart does not clear it. A name that exists and one that does not cost
  the same: one password hash. Inside fifteen minutes:
  - five failures for a name from one address: that address waits, on that name, until the oldest is fifteen minutes old;
  - twenty failures from one address, whatever the names: that address waits;
  - five failures on a name from anywhere: an address that has failed on it itself must leave a gap before its next try
    that doubles with each further failure (one second, up to fifteen). An address with no failure of its own is let
    past, so the owner gets in while a stranger fails elsewhere;
  - fifty failures on a name from anywhere: every try on that name waits that gap, whatever address it claims. So a
    guesser who can come from many addresses, or invent them, gets fifty quick tries on a name and then four a
    minute; and for as long as they keep at it, the owner of that name is mostly kept out too. That is the price of
    not letting a name be guessed without limit, and it takes fifty addresses to cause, not one.
  Changing a password is limited the same way (five wrong current passwords and it waits), and a change that was
  made answers that it was: it no longer signs in again to make the new session.
- **Which address, and what is trusted.** On a machine of its own: the connection's. Behind a proxy (hosted mode):
  **nothing, until it is told**. `ARCHITECT_CLIENT_ADDRESS` says where the proxy states the caller's address:
  `x-real-ip`, `xff:1` (the rightmost entry of `X-Forwarded-For`), `xff:2`, or `peer`. Left unset, no header is
  believed, every caller is the same unknown one, and sign-in is limited by name alone: five wrong passwords and that
  name waits fifteen minutes, whoever tries. That is the old behaviour, lockout by a stranger included, and it is the
  safe default: a header the caller can write must never be what a limit counts. The leftmost entry of
  `X-Forwarded-For` is never read. **Not established for Railway**: its staff's recent answers say the edge replaces
  `X-Real-IP` and `X-Forwarded-For` with its own, older answers disagree, and one user's measurement found two
  entries in `X-Forwarded-For`. To find out on a host: set it, sign in as the admin, and read *Your address, as
  counted* in Settings; it must be your own address and must not change when you send that header yourself with curl.
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
flight when the cap is reached finish, so several chats asked at once can overshoot by those calls. A call is never
counted as free: when the ledger cannot be written (the store busy past its patience) the write is tried again, and
if it still fails the turn stops with a message saying so. When a reader goes away while the model is writing, what
was sent and what had been written is put on the ledger as an estimate (about four characters a token), since the
provider's own figure never arrives. A call that errors at the provider before it returns its usage is not counted.
The admin has no cap unless one is set. It is a budget guard, not a rate limit.

**What a call counts for.** Claude models: Anthropic's list price. The OpenAI models in the table in `chat.py`
(GPT-6.1 Sol and Terra, GPT-6 Astra and Luna, GPT-5.x): their list price as reported in November 2026, looked up on
2026-11-24 and not checked against an invoice. `ARCHITECT_PRICE_IN`, `ARCHITECT_PRICE_OUT` and
`ARCHITECT_PRICE_CACHED` (USD per million tokens) replace the table for any model that is not Claude. A model with
no price is capped at the Sonnet 5 rate and the admin panel shows its billed amount as unknown, never as zero. A
flat-rate route (a ChatGPT subscription through Codex) bills nothing per call and is still capped.

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
everything, those two libraries' own dependencies included, with `constraints.txt`.

**What the scan cannot see.** It reads text. A picture or a recording (36 files in the export of 2026-11-24: the
screenshots and clips under `docs/img/` and the guide) is scanned as bytes only, so a private word shown in a picture
is not found. The tool says so each time it runs and names the files. They are made from the Caldergate demo by the
capture tools, which is the control; nobody has looked at each frame for this.

**The built web app.** The JavaScript the server ships (`static/app`) is built from `web/` by `npm run build` and
committed. It has six runtime dependencies (React, react-dom, DOMPurify, marked, mermaid, cytoscape), fixed by
`web/package-lock.json`. `npm audit --omit=dev` reported no known advisory on 2026-11-24. Neither review read the
built bundle itself, and nothing proves the committed bundle is what that source builds to: rebuild it before
publishing if that matters to you.

**Not pinned.** `constraints.txt` fixes versions, not hashes: a package re-published under the same version would
install. The base image (`python:3.12-slim`) is a tag, not a digest, and `git` is installed from the distribution at
whatever version it has that day. Deferred on 2026-11-24, not forgotten: a hashed lock file has to be made from
Linux wheels and proved by building the image, and the image could not be built in the session that did this work.

## Known limits, in one place

1. One file, one process, no encryption at rest: isolation depends on one check, with one exception (the admin's delete).
2. Document and PDF parsing is not sandboxed; hostile PDFs are only lightly tested.
3. Document text can steer the model's answer and its five writes inside the workspace.
4. Open mode trusts everyone who can reach the port; hosted mode trusts the proxy in front of it, and which header
   that proxy sets with the caller's address has not been established for Railway (see Sessions, sign-in and CSRF).
5. One address can be locked out of a known username by failing on purpose from that address; the username itself no
   longer can. Behind a proxy that hides addresses, everyone shares one.
6. A quoted word or two, or a single-quoted or italic phrase, that is not in the section word for word is shown as
   not checked: it is neither verified nor flagged.
7. The Docker image was built and run on 2026-11-14 from the public repository: on one machine (healthy, both demo
   workspaces, non-root) and in hosted mode with a volume (sign-in, Secure cookies, the security headers, 401 when
   signed out, logins and sessions kept across a restart). The build installs with `constraints.txt` on Linux. Not yet
   tried: `docker compose up` itself, and a question with a real model key inside the container.
   **On Railway it was not non-root**: a volume Railway mounts is root's, so the service ran with `RAILWAY_RUN_UID=0`
   and the server was root. Since 2026-11-24 the image starts as root for one step (`docker-entrypoint.sh` makes the
   volume the app's own) and then drops to uid 10001 for good, so that setting can be removed. **That change is
   unverified locally: the image has not been built or run on the machine it was written on** (its Docker was not
   working), so its first real build is the host's. Only the script's paths for a user that is not root were run, in
   a plain shell. For that reason the entrypoint fails loudly: if it cannot create or chown the data folder, cannot
   find `setpriv`, cannot drop to uid 10001, or that user cannot write the folder, it prints one plain sentence
   starting `architect entrypoint: STOPPED.` to the deploy log and exits 70 without starting the server; it never
   falls back to running as root. When it works it prints which uid the server runs as. Read that line in the first
   deploy's log; until it has been seen, treat the hosted server's user as unknown.
   The parse cache is a Python pickle, which runs code when loaded. Nothing a login sends is written where it is
   read from, and it is opened only when it carries a keyed hash made with a key kept in the store, not beside it.
8. Workspace sharing (teams, Private and Shared) was added on 2026-11-24 and reviewed the same day, at `bf13414` in
   the private history, before it was published. The review found one high finding that predates sharing (a note
   scoped to a Planual rule listed other workspaces' notes on the same rule: title and first 200 characters), five
   medium and five low. All are fixed, each with a test that failed first (`tests/test_review_sharing.py`). The fixes
   themselves have not been reviewed again.
   A second review the same day covered everything else changed since 2026-11-13. Two high (script injection on the
   estate report page; one document upload holding the store's write lock for minutes, with model calls missing the
   ledger meanwhile), five medium and eleven low. Fixed with tests that failed first (`tests/test_review_delta.py`,
   `tests/test_review_delta2.py`), except what this file says is deferred or not established: dependency hashes and
   the base image digest, the Docker user change (made, not built), which header Railway's edge sets, and fairness
   beyond one heavy job of each kind per login.
   A third, independent reviewer then attacked those fixes (at `5e599d8`). It closed the three high findings and
   left or found fifteen more, fixed the same day with tests that failed first (`tests/test_review_third.py`): memory
   through an archive's tables, a chat's title reaching the tracer, a call not counted on clients that do not
   stream, sign-in limits that trusted a caller's header, an edit guard that a cut-off sentence passed, a restored
   copy shared on to another team, and smaller ones. Still true after it: a guesser with fifty addresses can keep
   one name mostly out while they keep guessing; a maker can copy out what they can read; reading a legitimate
   export of hundreds of MB takes memory several times its size, and a backup can carry one that large; the fixes of
   this third pass have themselves not been reviewed.
9. Not looked at by either review: `codex.py`, `openai_compat.py`, `cli.py`. The builder read them for shell calls,
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

**Still open, not accepted:** the Docker image is built and run, but no question has been asked with a real model key
inside it and `docker compose up` itself has not been tried. Passing the demo script in the container is a step before
any Railway deploy.
