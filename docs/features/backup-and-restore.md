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

A restore makes a new workspace, beside any workspace the backup was taken from. Every id in it is made again by this
server: the workspace's, and those of each upload, chat, answer, note, document, section, proposal and citation,
wherever they appear, in the rows and in the text of the answers. A chip in an old answer still opens: it carries the
new id of the same thing. A link to the old workspace or to one of its chats, kept outside the app, does not.

Everything restored is the restorer's: each chat, question, note and document is under their login. Who the backup
says wrote it is kept beside it as text.

A backup taken from a shared workspace that held anything another login added says so, and the copy restored from it
cannot be shared with a team until the admin allows it (*Admin*, *Workspaces*, *Allow sharing*). The page says why.

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
- every id in it must be in the shape this server makes (`c-` and ten characters, a date and a time and a random
  part, and so on), and is then replaced by a new one. So nothing in an archive can collide with what the store holds,
  a restore cannot learn that an id exists, and nobody can make someone else's backup unrestorable by restoring
  something first;
- an author named in it is never taken as a login of this store;
- its tables and files are held to size limits by what the zip declares, before anything is unzipped, and again as
  they are read: a table may be up to 64 MB and 200,000 rows, and one with more structure than a table has (a few
  kilobytes of zip can hold tens of megabytes of empty objects) is refused before it is parsed. An export file is
  streamed to disk and capped at the upload limit. A file of megabytes that packs two hundred to one is refused as
  padding;
- a backup whose exports cannot be read is not kept: nothing of it stays in the store or on the volume;
- a path inside it that would leave the workspace's folder is refused.

**Why the workspace id is never taken from the file.** A workspace's folder is named by its id. On a disk that
ignores case (Windows, macOS by default) an archive naming an existing id in capitals was a second workspace to the
store and the same folder on disk: its backup read the other's transcripts, and its delete removed the other's
folder. On Linux, where the hosted instance runs, the two names are two folders and nothing was shared, but the
restore no longer depends on the disk: the id is made by the server, so it matches nothing an archive can name.

**What this does not stop.** Whoever can read a workspace can copy what they read, by a backup or by hand. The
share lock on a restored copy limits one thing: sharing that copy on, inside this instance, with a team its other
authors were never in. It is said in the backup as a plain fact, and a backup is a file its owner can edit.

## How it is built

Read `src/anaplan_architect/orac/backup.py`: `collect` gathers a workspace's rows, `export_estate` writes the zip,
`inspect_archive` and `check_closed` decide whether an archive may be restored, `import_estate` restores it in one
transaction. Tests: `tests/test_stage5.py`, `tests/test_restore_safety.py`, `tests/test_access.py`,
`tests/test_documents.py`.
