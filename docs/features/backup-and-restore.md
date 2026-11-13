# Backup and restore

## What it does

A workspace can be taken away as one zip and put back, here or on another server, with everything still attached:
old answers still open the evidence they cited.

## How to use it

- **Back up**: Workspace page, *Workspace settings*, *Download a backup*. One `.architect.zip`.
- **Restore**: *New workspace*, *Or restore a backup*. Choose the file; the page shows what it holds (name, models,
  counts, when it was taken) before you restore. You can restore under another name.
- From the console: `anaplan-architect backup --data DATA --estate NAME` and
  `anaplan-architect restore FILE --data DATA`.

A restore keeps the original ids, so a workspace that is already in the store cannot be restored on top of itself:
delete it first, or restore on another server.

## What a backup holds

The workspace's models and their export files, every upload (snapshot) with its parse, the project documents (their
text by section and the objects each section names), notes, chats with their answers and citations, decisions and
proposals.

No logins, passwords, sessions, settings or audit rows. No keys.

## What a restore refuses

A backup is a file its owner can edit, so a restore trusts nothing in it:

- it must hold exactly one workspace, the one its manifest names;
- every row must point only at that workspace and at rows the same archive carries. A chat held on another
  workspace's upload, a note for another workspace, a citation onto someone else's snapshot: any of these and the
  whole archive is refused, with nothing written;
- none of its ids may already be in the store;
- its tables and files are held to size limits by what the zip declares, before anything is unzipped;
- a path inside it that would leave the workspace's folder is refused.

## How it is built

Read `src/anaplan_architect/orac/backup.py`: `collect` gathers a workspace's rows, `export_estate` writes the zip,
`inspect_archive` and `check_closed` decide whether an archive may be restored, `import_estate` restores it in one
transaction. Tests: `tests/test_stage5.py`, `tests/test_restore_safety.py`, `tests/test_access.py`,
`tests/test_documents.py`.
