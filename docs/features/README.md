# Features

One page per feature. Each says what it does, how to use it, and how it is built, with the file to read.

| Page | What it covers |
|---|---|
| [Workspaces and logins](workspaces-and-logins.md) | A workspace as an isolated unit, memberships, sign-in, the demo workspaces, deleting a workspace |
| [Documents](documents.md) | Project documents as cards and sections, search, quotes and how they are checked |
| [The line-item index](line-item-index.md) | Exact counts and filters over every line item of every model |
| [The five answer patterns](answer-patterns.md) | Why, build plan, overview, improve, implications, and the exact count |
| [Build plans](build-plans.md) | A plan as instructions, and what code checks before it is shown |
| [Concise and Full](concise-and-full.md) | The two answer modes, explain, show diagram, expand to Full |
| [The context budget and context view](context.md) | What the model is given for an answer, and what is left out |
| [The run timeline](run-timeline.md) | The calls behind an answer, in order, with no outside account |
| [The validator](validator.md) | What is checked before you see an answer |
| [Tracing](tracing.md) | LangSmith, and each login's own level |
| [Spend caps and the admin panel](spend-caps-and-admin.md) | The ledger, the cap, creating logins |
| [Backup and restore](backup-and-restore.md) | One zip per workspace, and what a restore refuses |
| [Model providers](model-providers.md) | Anthropic, Bedrock, Azure, any OpenAI-compatible endpoint |
| [Hosting](hosting.md) | One machine, a server for several people, Railway |

See also: [the walkthrough](../WALKTHROUGH.md), which clicks through all of it on the demo, and
[what it protects and what it does not](../SECURITY.md).

The page says **workspace**; the code and the store say **estate** (table `estates`, routes `/api/estates/...`).
They are the same thing. The store's own `workspaces` table is the instance itself.
