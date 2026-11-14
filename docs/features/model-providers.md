# Model providers

## What it does

The app needs a language model to write its answers. Which one is one setting. The rest of the app does not know
or care which it is, and Settings shows where your questions go so nobody has to guess.

## How to use it

Copy `.env.example` to `.env` and fill in one block; the file has one per provider. `.env` is gitignored and stays
on the machine. Docker reads the same file; on a server, set the same names as service variables.

| `ARCHITECT_PROVIDER` | Needs |
|---|---|
| `anthropic` | `ANTHROPIC_API_KEY`; `ARCHITECT_MODEL` (default `claude-sonnet-5`) |
| `bedrock` | Claude on Amazon Bedrock: AWS credentials from the usual chain, `AWS_REGION`, `ARCHITECT_MODEL` = the Bedrock model id |
| `azure` | Azure OpenAI: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` |
| `openai` | Any OpenAI-compatible chat-completions endpoint, OpenAI's own or one inside your organisation: `OPENAI_BASE_URL`, `OPENAI_API_KEY` if it needs one, `ARCHITECT_MODEL` |
| `codex` | A ChatGPT subscription through `codex login` on the server |
| `auto` (default) | Anthropic when a key is present, else an OpenAI-compatible endpoint when one is set, else Codex when its login exists, else none |

With no model the app still reads exports, draws the dashboard, counts line items and shows documents; it cannot
answer questions, and says why.

## What leaves the machine

Exports, documents, notes and chats stay on the server's disk. When someone asks, the question, a summary of the
workspace (names, formulas, sizes), the document cards and whatever the tools pulled for that answer go to the
provider, and nowhere else. The [context view](context.md) lists exactly what went for each answer. With an endpoint
inside your organisation, nothing leaves it.

## Which model

The answers depend on the model following instructions and calling tools well. It was built and tried on recent
large models. A small local model will run and will be worse at plans and at quoting; the validator will flag more.

## How it is built

- `resolve()` in `src/anaplan_architect/provider.py` reads the environment and returns the client to use.
- Everything speaks the Anthropic messages shape inside the app. `src/anaplan_architect/openai_compat.py` translates
  to and from chat-completions for Azure and OpenAI-compatible endpoints; `src/anaplan_architect/codex.py` does the
  same for the Codex route, which is an undocumented interface and may stop working.
- Extras to install: `.[llm]` for Anthropic, `.[bedrock]`, `.[openai]` for Azure and OpenAI-compatible.
- Tests: `tests/test_provider.py`.
