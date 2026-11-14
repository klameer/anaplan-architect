# Walkthrough: see for yourself that v0.2 works

Each entry: where to go, what to do, what you should see, why it shows that, and what is limited. Every entry was
run on 2026-11-13 against the seeded demo. How each was run is in the last column of the table at the end.

Figures marked *varies* come from the model and change between runs. Everything else is fixed by the demo files.

## 0. Launch and reset

1. Start the app: `.venv/Scripts/anaplan-architect serve --data out/data --port 8765` (in this checkout, the
   launch entry `architect`).
2. Open `http://localhost:8765` and sign in. (A fresh data folder with no logins, bound to localhost, opens with no sign-in.)
3. Reset the demo: **Settings** (bottom left) then **Reset the demo**. Or `python tools/demo.py reset --user karim --password <yours>`.
4. Optional, about 8 minutes: `python tools/demo.py run --user karim --password <yours>` asks the nine scripted questions so their answers are
   already there. It prints a table and exits 1 unless every verdict is clean.

Your other workspaces are not touched by a reset: only your two demo workspaces are replaced.

Entries 17 to 20 need an admin and a second, non-admin login. On a store that has them, sign in as the second login
in a private browser window. To try it from nothing instead, start a second instance with its own data folder on
port 8766: set `ARCHITECT_ADMIN_USER=admin` and `ARCHITECT_ADMIN_PASSWORD` to a password of your own, then
`anaplan-architect serve --data out/fresh --port 8766`; the admin is created on first start.

## 1. Workspaces

- **Where**: the dropdown at the top of the sidebar.
- **Do**: open it. Pick **Caldergate Stores**. Then pick **Caldergate Distribution Group** again.
- **See**: both demo workspaces listed, and the line "A workspace is separate… Nothing is remembered across
  workspaces." After switching, the page title, the counts in the nav and the chat list all change. The Stores
  workspace shows none of Caldergate's chats.
- **Why**: every page and every chat belongs to one workspace; the sidebar lists only what is in the one selected.

### Deleting a workspace

- **Where**: the workspace dropdown (hover a row, the bin at its right), or Workspace page, **Workspace settings**,
  **Delete workspace…**. The admin can also do it for any workspace from **Admin**, **Workspaces**.
- **Do**: create a throwaway workspace first (entry 3), then press its bin.
- **See**: a dialog with the workspace's name, **What goes with it** (its models and their exports, documents, chats,
  notes, decisions and dependencies, each with a count), "There is no undo", and a box to type the name. **Delete
  workspace** stays off until the name matches exactly.
- **Do**: type the name, **Delete workspace**.
- **See**: "Workspace deleted." and the app on another of your workspaces. Delete your last one and you land on
  "No workspaces yet".
- **Why**: only a member can delete a workspace, and the admin; to any other login it does not exist.

## 2. The dashboard

- **Where**: **Workspace** in the nav, with Caldergate Distribution Group selected.
- **See**: 4 models, 58 modules, 426 line items, 145M cells, 35 / 42 tests found something. Then:
  - **Model map**: four cards left to right in columns, centred in the panel, none touching another: Data Hub, then
    Workforce Planning, then FP&A, then Board Reporting. The number on a feed sits in the gap between columns, never on
    a card. Data Hub to FP&A carries 5 and runs past Workforce Planning through a gap; FP&A to Workforce Planning is dotted and
    labelled retired, with its arrow pointing back.
  - **What was tested**: six rows with amber and green bars.
  - **Where the cells are**: `CAL05 Opex OLD` is the largest box (70M, 54%).
  - **Inside a model** (FP&A selected): **Who reads whom** (a grid of modules), **Where the calculation time goes**
    (`CAL05 Opex OLD` 50.8%), **Functions it leans on** (IF first), **Longest formulas**, **What the modules are for**.
- **Do**: click **Workforce Planning** in the "Inside a model" row.
- **See**: the effort panel says "No Calculation Effort column in this model's Line Items export".
- **Do**: click **ask** on any panel. A chat opens with that question.
- **Why**: every panel is read off the parse and the line-item index. A missing export column is said, not hidden.
- **Limited**: seven more panels were listed as candidates and are not built (formula complexity spread, calculation
  depth, dimensions, actions, unreferenced, documentation coverage, what changed).

## 3. Upload line items, modules and actions for several models

- **Where**: the workspace dropdown, **+ New workspace**.
- **Do**: name it. Add one row per model and choose its files from `examples/caldergate/exports/`: for each of the
  four folders, `Line Items.csv`, and optionally `Actions.csv` and `Modules.csv`. Create.
- **See**: each row's model name fills in from a file that carries one ("Caldergate FP&A - Line Items.csv" gives
  "Caldergate FP&A"). A file named only "Line Items.csv" leaves the name empty, and Create asks you to name that row:
  a model is never named after its export file. Then a new workspace with 4 models and 426 line items, and the same
  dashboard as the demo.
- **Why**: a workspace is built from exports alone. Line Items is required; Actions and Modules add the action and
  module panels.
- **Later uploads**: Workspace page, **Models and their exports**, upload a new set. It is parsed, then activated.

## 4. Documents

- **Where**: **Documents** in the nav.
- **See**: "6 of 20", the limit line ("Up to 20 project documents, 10 MB each… A scanned PDF is not read: there is
  no OCR"), and six cards. Each card: type, date, size, a summary, a strip with one bar per section, headings, the
  objects it names. The design decision record has 26 sections.
- **Do**: **Choose files** and pick any Markdown, text, Word or PDF file of your own.
- **See**: a seventh card within a few seconds, with its section count and, if it names a module such as
  `SYS05 FX Rates`, that module as a chip. Its summary is written by the model at upload when the server has one.
- **Do**: **Remove** on that card, confirm. Or **Replace with a new version** and pick a file.
- **See**: the card goes; or it comes back marked "version 2".
- **Why**: a document is split into sections and linked to the objects it names at upload. No embeddings: the index
  is SQLite's own full-text search.
- **Limited**: `.doc`, `.pptx` and `.xlsx` are not read and say so on the card.

## 5. Why was it built this way (Full)

- **Where**: **Chats**, **New chat**.
- **Type**: `Why is the account mapping written into the Forecast Opex formula instead of a lookup table?`
- **See** (about 25 seconds):
  - Kind **WHY · FULL**, the answer in a few lines.
  - **The passages**: a source card from "Caldergate FP&A: design decision record v1.2", section "4.3 Opex forecast
    logic", with the quoted sentence marked in green and the text around it in grey. *Varies*: usually a second card
    from "CR-031: Legal fees driver in the opex forecast".
  - The foot: **VERIFIED**, and "3/3 quotes found" (*the count varies*). A quoted word or two that is not in the
    section word for word is counted apart, as "1 quote not checked", never as found.
- **Do**: click the head of a source card.
- **See**: the drawer opens the whole section with the quote marked.
- **Why**: the model sees only document cards until it calls `search_documents` and `get_section`; code then checks
  every quote against the section it names.

## 6. A why with no document behind it

- **Type**: `Why is the margin module called CAL04 Margn?`
- **See**: the **Not recorded** card with Bert, and an answer that says no document or note gives a reason and then
  only what the estate shows. Verdict verified.
- **Why**: a why-answer needs a passage or an owner note. Without one it must say so; if the model fills a reason in
  anyway, the answer is headed "Not recorded" by code and flagged.

## 7. A build plan (Full)

- **Type**: `Give me a plan to build a lookup module that replaces the account mapping inside Forecast Opex.`
- **See** (about two minutes), top to bottom:
  - **Overview**: three or four plain sentences: what is built, why, what it replaces. *Varies*; on the last run it
    said the account IF chain in `CAL03 Opex.Forecast Opex` is replaced by a mapping Finance Systems controls, that
    planners keep entering drivers in `INP02 Opex Drivers`, and that legal fees stay out of it.
  - **What you will build**: a card per module, numbered in build order, with its dimensions as chips, its purpose in
    one sentence ("more" opens the rest) and, directly under it, its line items: name, format, dimensions, summary and
    the formula in full with "✓ valid". Then an amber card for each existing formula that changes, shown **from** and
    **to**. *Varies*: last run, `SYS03 Account Attributes` (exists, you add to it; line item `Opex Driver`),
    `CAL13 Opex Driver Values` (new; line item `Value`), and `CAL03 Opex.Forecast Opex` changed.
  - **What already exists that this uses**: Modules `CAL03 Opex`; Line items `CAL03 Opex.Forecast Opex`; Lists
    `Accounts`, `Cost Centres`. Click a blue or violet name: the drawer opens that object.
  - **Steps** ("follow them in order in Anaplan"), numbered, under a key to the number colours: green, build something
    new; amber, change something that exists (the switch-over); outlined, a check where nothing is built. Last run, 12:
    1. Create `LIS Opex Forecast Drivers`: a line item subset of `INP02 Opex Drivers` holding the driver line items.
    2. Open the existing module `SYS03 Account Attributes`. Leave its line items as they are.
    3. Add the line item `Opex Driver`: format List, no formula, an input.
    4. Create the module `CAL13 Opex Driver Values` with its dimensions.
    5. Add the line item `Value`, with its formula in a box under the step.
    6. In amber: in `CAL03 Opex`, replace the formula of `Forecast Opex`, shown **from** (today's IF chain) and **to**
       (the lookup). "This is the switch-over: do it last."
    7. to 12. Checks: compare `Forecast Opex` cell for cell against a saved baseline, check each account-to-driver
       pair, check who can edit the mapping, compare recalculation before and after.
  - One quiet line: "order checked: nothing is built before what it refers to · 2 of 2 formulas are valid Anaplan
    syntax · every name they use is in the model or built by this plan".
  - Last, under **Why this was wanted**: the passage from CR-031 that records the lookup as agreed in principle,
    quoted and checked. It sits after the plan, not above it.
- **Do**: **explain** under a step. **See**: that step's note opens in place.
- **Do**: **show the build-order diagram**; **CSV, one row per line item**.
- **Why**: the model proposes modules, line items, the existing formula to switch over and the checks; code parses every
  formula with the Anaplan grammar, checks every name against the model and the plan, refuses a change that would
  close a loop, sorts the order, and writes the numbered steps itself. A plan that fails any of it is not shown.
- **Limited**: a plan is a proposal. Nothing is built in Anaplan, and the formulas need an Anaplan builder's read. The
  exports do not hold list members or line item subsets, so a step that creates one is taken from the model's words,
  not checked. The module purposes run longer than one line.

## 8. Overview and improve

- **Type**: `Give me an overview of the build.`
  **See**: **How data moves** (the model map) and **Where the cells are**, then prose.
- **Type**: `How can we improve it?`
  **See**: a row "42 tests run … 5 on the plan", then five ranked cards. Card 01 is "Stop repeating text-to-item
  lookups (FINDITEM)…" with **TEST 1.4** and bars for cells and effort share. Card 03 is the `CAL05 Opex OLD`
  investigation, 70M cells, 50.8%.
- **Why**: the cards are the deterministic action plan over the 42 tests, not the model's opinion.

## 9. Implications of a change

- **Type**: `What are the implications of changing SYS05 FX Rates?`
- **See**: tiles "48 line items · 4 direct", "10 modules", "31M cells in reach", "3 actions", "2 other models,
  inferred". The **rings**: `SYS05 FX Rates` at the centre, seven rings, a dot per line item, module names around
  the edge. Below: **By module** (10 rows), **Actions** ("Import FX from Treasury file", last run 2023-11-02, in
  amber), **Other models**, **What this cannot see**.
- **Do**: click **Steps** above the diagram.
- **See**: the same reach as a grid, a row per module and a column per step away.
- **Why**: reach is counted over the formula graph, each line item once at its shortest distance.

## 10. Concise mode, with explain and show diagram

- **Where**: the **Concise / Full** switch on the composer. Next to it, the model menu ("Whole workspace"): open it and
  the list is dark, the models readable, the chosen one green with a tick.
- **Do**: switch to Concise. Type `Give me a plan to build a lookup module that replaces the account mapping inside
  Forecast Opex.`
- **See**: kind **BUILD PLAN · CONCISE**, two lines of overview, then **Steps** alone (the same numbered instructions as
  in entry 7, ending with the switch-over and the checks) and **What already exists that this uses**. No tables, no
  diagram.
- **Do**: **show diagram** beside Steps. **See**: the build order opens in place.
- **Do**: **explain** under a step. **See**: that step's note opens in place.
- **Do**: **expand to Full** under the answer. **See**: the full plan, with no new question asked.
- **Type** (still Concise): `What are the implications of changing CAL03 Opex?`
  **See**: a few lines and the tiles (23 line items, 6 modules). **show diagram** draws the rings.
- **Why**: the figures and the plan are drawn from data the tools returned, so Full can be shown without asking again.
- **Limited**: **explain** under an answer other than a plan asks a follow-up question; it is not instant.

## 11. An exact count over a large model

- **Where**: switch to **Caldergate Stores** (one model, 5,403 line items). New chat.
- **Type**: `How many line items use FINDITEM, and which modules are they in?`
- **See**: kind **COUNT**. A large **48**, "line items of 5,403", and the first rows. The answer names the
  Flagship and Online modules.
- **Why**: every line item is a row in an index written from the parse. The tool returns a count and at most 25
  rows; the list never reaches the model.
- **Limited**: Caldergate Stores is generated (`tools/make_store_model.py`), not a real model.

## 12. The context view

- **Where**: under any answer, the green chip **context 16.5k / 32k** (*the figure varies*).
- **See**: the total against 32,000; a bar split by kind; **Given to the model**, one row per item with why it is
  there and its size (instructions, the estate in brief, 6 document cards, owner notes, each tool result, each
  section pulled); **Left out**, for the why-answer about 18,000 tokens, including "Caldergate FP&A: design decision
  record v1.2 · 25 other sections" (*24 or 25*).
- **Why**: each item is recorded as it is sent. Sizes are estimates at four characters to a token, and the panel
  says so.
- **Limited**: the instructions and the estate summary take about 12,000 tokens before any question.

## 13. The run timeline

- **Where**: the same panel, below the context.
- **See**: numbered steps on one time axis: model, `list_models`, model, `search_documents`, model, `get_section`
  (once or twice), model (the answer), then the validator with "clean". A caption with calls, seconds and tokens.
- **Why**: built from what the turn stores. No outside account is needed.

## 14. Evidence on any name

- **Do**: click any blue or violet chip in an answer, such as `CAL03 Opex.Forecast Opex`.
- **See**: the drawer with the formula, dimensions, what it uses and what uses it, and the export row it came from.

## 15. Settings

- **Where**: **Settings**, bottom left.
- **Do**: switch **Answer mode** to Concise, open a new chat.
- **See**: the composer starts on Concise. Switch it back.
- **Also there**: Reset the demo; what is stored here and what is sent to the model, with the provider and endpoint;
  tracing; About, "Built by CodelessOps".

## 16. Notes, Dependencies, Improve

These three pages are as in v0.1, inside the new shell. Not restyled.

## 17. Sign in

- **Where**: the app's address, signed out (Settings, Sign out), or a private window.
- **See**: a sign-in page with Username and Password, "There is no signup", and a box "Before you upload" with the
  test-instance notice.
- **Do**: sign in as the admin.

## 18. The admin panel, and creating a login

- **Where**: **Admin**, bottom left (admin only).
- **See**: tiles, then a row per login: last seen, sign-ins, workspaces, uploads, documents, questions, metered, cap.
  Below, **Workspaces**: every workspace on the instance by name, with its members and counts, and **Delete**. The
  admin cannot open any of them.
- **Do**: under **Create a login**, type a username and a name, leave "with the demo workspaces" ticked, **Create**.
- **See**: a green box with the username and a generated password, shown once.
- **Do**: open a private browser window, go to the app, sign in with them.
- **See**: two workspaces, that login's own copies of the demo.

## 19. A second login cannot see the first one's workspace

- **Do**: as the new login, ask one question in Caldergate Stores (use entry 11). Copy the address of that chat.
  Create a second login as admin and sign in as it in another private window. Paste the address.
- **See**: nothing opens; the app returns to that login's own workspaces. The admin cannot open it either.
- **Why**: every request that names a workspace, or anything inside one, is checked against membership in one
  place; to a non-member it answers 404.
- **Check from the command line**: `python tools/walkthrough_check.py --base <address> --admin <admin>
  --password <password>` creates two logins and runs 17 checks, including this one.

## 20. The spend cap tripping

- **Do**: as admin, on the first login's row press **Cap**, enter `0.01`. As that login, ask anything.
- **See**: a message "This login has reached its spend cap: $0.03 used of $0.01…" and no answer. The admin row
  shows the cap in amber, "reached". Reading still works.
- **Do**: set the cap back to `2`.
- **Do**: delete one of that login's chats, then look at its row in Admin again.
- **See**: Metered has not gone down. Deleting chats or a workspace gives no budget back.
- **Why**: spend is a ledger per login, one row per model call. The cap is checked before every model call, so a long
  answer stops part way with "(stopped: this login has reached its spend cap…)" rather than running on. The summary
  written when a document is uploaded counts too.
- **Limited**: on the Codex route nothing is billed, so the cap counts tokens at Claude Sonnet list price. Chats asked
  at the same moment can overshoot by the calls already in flight.

## 21. Starting it from the Docker image

```bash
python tools/build_wheels.py
```

```bash
docker compose up --build
```

- **See**: `http://localhost:8765` with no login and the two demo workspaces already there.
- **Run** (2026-11-14, from the public repository, started with `docker run`): healthy in about six seconds with
  both demo workspaces, non-root, about 86 MB at rest. In hosted mode with a volume: sign-in, Secure cookies, the
  security headers, 401 when signed out, and a restart (about a second) that keeps the login and its session.
- **Not yet tried**: `docker compose up` itself, and a question with a real model key inside the container.

## 22. Tracing to LangSmith: each login's own choice

- **Needs**: `LANGSMITH_API_KEY=…` in `.env` and a restart. A tracing-only key is enough.
- **Where**: **Settings**, **Tracing your questions**.
- **See**, signed in as the admin: three buttons, **Off / Structure / Full**, with **Full** on, and the words "You
  run this instance, so your own questions are traced in full… Nobody else's are: each login decides for itself, and
  you cannot turn it on for them."
- **Do**: ask any question. **See** in LangSmith, project `anaplan-architect`: a run tree named by the chat, a run for
  the question under it, and under that each model call, each tool call by name with what it returned, and `verify`
  with the verdict.
- **Do**: sign in as the non-admin login in a private window, open Settings.
- **See**: **Off** is on, with "the person who runs this instance will be able to read what you send" and "does not
  delete what was already sent". The sign-in page said the same: "Your questions are not sent to it… unless you turn
  that on for yourself in Settings."
- **Do**: ask a question as that login. **See**: nothing new in LangSmith.
- **Do**: press **Structure**, confirm the question it asks, and ask again.
- **See**: a run tree named "conversation" with "turn 2" under it: tool names, sizes, tokens and timings, and every
  text shown as a character count. Settings now says "You chose Structure on" with the date and time.
- **Do**: as the admin, open **Admin**. **See**: a **Tracing** column with each login's level, and nothing to change it.
- **Why**: on a shared instance the operator and LangSmith would otherwise hold other people's questions and passages.
  The level is read for every question from whoever asked it, so a change applies from the next question.
- **Run**: the key was checked on 2026-11-13. It is a tracing-only key on the US endpoint: a write is accepted, every
  read is refused ("not allowed for tracing keys"), so that a run tree arrived could not be read back through the API
  and was not looked at in LangSmith's own page by me. One real question was asked as the admin with tracing on; the
  tracer reported no error. The levels and who may set them are tested against a recording client
  (`tests/test_trace_levels.py`) and in a real browser for both logins (`tools/ui_check.py --member …`).

## 23. The capture set

```bash
.venv/Scripts/python tools/captures.py --user admin --password <the capture store's admin> --prepare --docs
```

- **Needs**: a store made for it, so no real name is in any frame: a login called `admin`, nothing else. `--prepare`
  writes the demo, makes two demo logins and asks the scripted questions (about ten minutes of model time). Clips
  need `ffmpeg` on the path.
- **See**: `out/captures/stills/` (each feature at 1600x1000 and at 1080x1350), `out/captures/clips/` (six clips of 10
  to 30 seconds, no audio), `out/captures/manifest.json` (file, feature, the question asked, viewport), and, with
  `--docs`, the images the README and the feature pages use, copied into `docs/img/`.
- Capture mode (`?capture=1`) hides the signed-in name, the provider line and the server's data folder.
- **Run**: 78 stills and 6 clips, nothing missed.

## 24. Bert, and the name

- **The name**: `/architect`, "your Anaplan build buddy". On the sign-in page, the browser tab and Settings, About.
- **Where Bert is**, each a still beside the page's own words:
  - the sign-in page, top right, saying hello;
  - the Workspace page, beside the ask box;
  - Documents with none yet, and while an upload is being read;
  - New workspace when you have none, and while the exports are parsed;
  - a chat while the answer is being worked on, with "Still investigating.";
  - a chat when a question got no answer, and when the spend cap is reached;
  - the frame of a **Not recorded** answer (entry 6);
  - Admin, when there are no other logins or no workspaces;
  - an address that opens nothing (try `#/e/<a workspace>/nope`): "Nothing at this address".
- **Where he is not**: inside an answer. Not in its text, figures, source cards, diagrams, plan, context view, run
  timeline or verdict. Open any answer and look.
- **Why**: he is a companion for the waiting and the empty moments; a figure with a mascot on it is trusted less.
- **Check**: `python tools/bert_check.py --user … --password … --empty http://localhost:8767 --empty-password …` walks
  to each place, saves a still under `out/bert/`, and opens every answer in the demo workspaces to confirm he is in
  none of them. 51 checks passed; 14 stills.

## How each entry was run

| Entry | How it was run |
|---|---|
| 0 | `tools/demo.py reset`, and `tools/demo.py run` twice on a fresh data folder: 9 of 9 clean both times |
| 1, 2, 4 to 15 | `tools/ui_check.py`: a real browser clicking through as the admin login, 71 checks passed (the model map, the scope menu, deleting a workspace and the plan as instructions among them) |
| 3 | the page opened in the browser; the upload itself only through the route it posts to (tests) |
| 16 | not re-checked beyond the pages opening |
| 17, 18 | `tools/ui_check.py` (sign-in, admin panel); creating a login through `tools/walkthrough_check.py`, not the form |
| 19, 20 | `tools/walkthrough_check.py`: 17 checks passed; and `tests/test_access.py` over every route |
| 21 | not run (Docker engine); a clean install standing in for the image was run |
| 22 | not run (no key) |
| 23 | `tools/captures.py` on a capture store: 78 stills, 6 clips, a manifest |
| 24 | `tools/bert_check.py`: 51 checks passed, in a real browser, on the demo workspaces and an empty scratch store |

## Mocked, limited or not built

- **Design sheet** (`#/design`): still there, still on mock data. It is the P0 record, not the app.
- **Bert** stands around the answers, never in them (entry 24). He is a still everywhere: nothing of him moves.
- **Light theme**: none.
- **OCR**: none.
- **Docker image**: built and run; `docker compose up` itself and a real-key question inside the container not yet tried.
- **Railway**: `railway.json` is written; no project exists and nothing is deployed.
- **LangSmith**: not run against a real key.
- **Public repo**: prepared locally, not pushed.
- **Moment 9** (running it yourself in a few minutes) is not captured: it needs the Docker run.
