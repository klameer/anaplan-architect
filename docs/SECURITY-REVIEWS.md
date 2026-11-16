# Security reviews

A security review is run when the maintainer calls for one, not on every change, and each review is tied to a
commit. This is the log of those reviews, newest first, so anyone can tell which version has had a review run against
it. **Commits after the newest entry have not been reviewed.**

## How to read it, and how to check it

- **A review is run on one commit of the public repository.** Call it N. The entry below names N by its full SHA.
- **A file cannot name the commit it is in.** So the entry that names N is added in the next commit, N+1. N+1 changes
  nothing but this log and the documents: no code.
- **N is tagged.** The reviewed commit carries an annotated tag, `reviewed-YYYY-MM-DD`, on the public repository.
- **You can verify all three.** `git show reviewed-YYYY-MM-DD` shows N. `git diff --stat N N+1` lists only files under
  `docs/` and the `README.md` and `SECURITY.md` at the root. Anything else in that diff means the rule was broken.
- **Code changed after N is not covered by the review of N.** The latest entry is the latest reviewed commit, not a
  statement about whatever is newest. Publishing does not wait for a review: between reviews there are commits no
  review has seen. `python tools/make_public.py --check` in the maintainer's checkout lists the files of code that
  have changed since the last reviewed commit.

## What a review here is, and is not

Each review is done by a separate AI reviewer that had no part in building the code. It is given the code and not
the builder's conclusions. It is not a human audit. It is not a penetration test of a running instance. It reads the
source for the ways a workspace, a login, an upload, a model's output or a published file could be misused.

You are invited to run your own. The code is MIT licensed; see [SECURITY.md](../SECURITY.md) for how to tell us what
you find, and [what it protects and what it does not](SECURITY.md) for the design as its builder describes it.

## What an entry holds

The date; the commit reviewed, by full SHA, and its tag; the scope (the whole code, or the changes since the commit
reviewed before); who reviewed; the findings by severity, a line each; what was fixed and in which commit; what was
accepted as a limit, and by whom.

---

## 2026-11-13: the first review, before the public repository existed

- **Commit reviewed:** `408cf354875182822dad99cb05f295d6c07247df`, in the private history this project was built in.
  The public repository did not exist yet, so there is no public commit and no tag for this review. The public
  repository was first published the same day from a later commit, after the fixes below.
- **Source commit (private history):** `408cf354875182822dad99cb05f295d6c07247df`
- **Public commit:** none.
- **Tag:** none.
- **Scope:** the whole code as it stood, with a separate independent code review of the same commit beside it.
- **Reviewer:** a separate AI reviewer with no part in building it. Not a human audit. Not a penetration test of a
  live instance: no instance was running in public.
- **Not looked at:** `codex.py`, `openai_compat.py` and `cli.py` were read by their author only.

**Findings.** Ten, numbered S1 to S10 by the reviewer. The severity the reviewer gave each was not kept in this
repository, so none is claimed here; they are listed in the reviewer's order.

| | Finding | Fixed in (private history) |
|---|---|---|
| S1 | A restored backup could reach into another login's workspace: an archive could carry rows that pointed outside itself, and ids were short enough to guess | `fe15b8a` |
| S2 | Spend could be run up or hidden: no ledger per model call, no limit on a question's length, and the document limit could be sidestepped | `df3eafe`, `f9d5e84` |
| S3 | An answer, a note or a passage could make the browser call another site, and text read from a document could pass as the owner's word in a later prompt | `4939dfc` |
| S4, S5, S6, S8 | Four findings on running it for other people: cookies and transport behind a proxy, what a caller learns before signing in, no limit on failed sign-ins, and no limit on the size of a request or of what an archive unzips to | `6a19b86` |
| S7 | A note could borrow a citation or a model from another workspace | `5b59429` |
| S9 | The public export could carry the local git identity or miss a file that is not text; the two libraries were pinned to tags, not commits | `2b01c62` |
| S10 | With content turned off, a trace could still carry text in the names of its fields | `b45e450` |

All ten were fixed, each with a test that failed first. The design document was then rewritten to match the code
(`41e9904`).

**Accepted as limits**, by Karim Lameer on 2026-11-13, for a test instance whose logins he hands out:

1. Chats asked at the same moment can pass a spend cap by the calls already in flight.
2. Anyone can keep a known username locked out by failing to sign in on purpose.
3. Four of the model's five write tools are documented, not marked: a model steered by a hostile document can call them.
4. Workspace ids made before 2026-11-13 are short and still resolve.
5. The image's pins were resolved on Windows, and the base image is named by tag, not digest.
6. Hostile PDFs are lightly tested: six malformed files, none built to exhaust the parser.
7. `codex.py`, `openai_compat.py` and `cli.py` were read by their author only.

**Since this review.** The code has changed a great deal: the public repository, hosting for several people at once,
new answer patterns, an editing pass, Planual flags and more. None of that is covered by this entry. It is covered
when the next entry says so.
