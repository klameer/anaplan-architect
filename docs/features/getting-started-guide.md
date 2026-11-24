# The getting-started guide

## What it does

A guide for someone who has just been handed a login. Not for an engineer. It walks through what they will see, in
the order they will meet it, in about ten minutes: signing in, workspaces (Private and Shared), which Anaplan exports
to bring and where to find them, documents, asking, reading an answer, Concise and Full, build plans and the Planual
flags, what a change touches, notes, what the tool cannot see, the spend cap, tracing, and who to ask.

Each screen is a real capture from the Caldergate demo with two or three numbered arrows on it. The arrows are drawn
over the picture and the callouts are a list under it, so every word is text: it can be read aloud, searched and
translated. Nothing moves.

It exists in three forms, made from the same source:

- **In the app.** *Guide*, beside Settings, open to every login. On a login's first visit a card offers it: *Open
  the guide* or *Not now*. Either way the card does not come back; the link stays.
- **As one file.** `docs/onboarding/getting-started.html`: the same guide with its images inside the file, no script
  and no outside request. Send it, or print it. It reads at phone width.

- **On the website.** `https://codelessops.com/anaplan-architect/getting-started/`: the same guide as a page of the
  /architect section, for someone who has no login yet. The README links to it.

## How to use it

Nothing to do for a new login: the card appears once.

To send the guide to someone before they have a login, send `docs/onboarding/getting-started.html`.

## Keeping it true

The guide is written once, in `src/anaplan_architect/guide/spec.json`: the sections, their words, the screens, and for
each callout the element it points at, by selector.

```bash
python tools/guide.py --password <the capture store's admin> [--ask]
```

That one command takes every screen again from the capture store, looks each callout's element up on the real page,
records where it is, and writes both forms. So an arrow cannot be left pointing at where a button used to be. If an
element is no longer on the page, the run stops and names it, and nothing is written.

Run it after any change to a screen the guide shows. `--ask` asks the three questions the screens need when the demo
login's workspace does not have them yet (three model calls).

## Limits

- The screens are Caldergate, an invented company. A reader's own workspace will look different in its names.
- Where to find each export in Anaplan is described in words, not shown: the tool has no access to Anaplan.
- It is in English. The text is real text, so a browser can translate it; nobody has checked a translation.

## How it is built

- `src/anaplan_architect/guide/` (`spec.json`, and `to_html` for the one-file form); `tools/guide.py` (the capture
  run); the generated `src/anaplan_architect/static/guide/guide.json` and `img/`.
- `GET /api/guide`; the `guide_seen` preference on `GET` and `PUT /api/prefs`.
- `web/src/views/Guide.tsx` (`Guide`, `GuideWelcome`).
- Tests: `tests/test_guide.py` (the path, the route, the dismiss state, every callout resolved, and the one file
  making no outside request).
