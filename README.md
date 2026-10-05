# Autonomous AI Task Worker — Prototype

A working prototype of an AI worker that takes a natural-language task and
autonomously completes it inside a simulated company environment (a mock
inbox + a mock internal system), following the loop:

**Goal → Understand → Plan → Execute → Observe → Adapt → Verify → Complete**

Built for the CentrAlign AI Engineering Intern problem statement.

## Example task

```
"Find the latest invoice from Company X, extract the amount and due date,
enter it into our internal system, and tell me once it is done."
```

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
```

## Run (CLI)

```bash
python main.py --reset "Find the latest invoice from Company X, extract the amount and due date, enter it into our internal system, and tell me once it is done."
```

`--reset` clears the mock internal system so you start from a clean state.
Each run prints the agent's reasoning, actions, and observations live, and
saves a full JSON trace to `logs/run_<timestamp>.json` as evidence.

Try other tasks too, without changing any code, e.g.:
```bash
python main.py "Find the invoice from Company Y and enter it into our internal system."
```

## Run (live web demo)

A minimal Flask UI (`public/index.html` + `api/index.py`) wraps the same agent
for a browser-based demo, deployable on Vercel:

```bash
npm i -g vercel          # if not already installed
vercel login
vercel env add ANTHROPIC_API_KEY   # paste your key when prompted
vercel --prod
```

Note: the web version runs with `interactive=False` — since a stateless HTTP
request can't pause and wait for real human input the way the CLI can, the
`ask_user` tool instead logs the question and tells the agent to proceed on
its best reasonable assumption, flagging that assumption in its final
summary. This is a deliberate, disclosed trade-off for the hosted demo, not
a hidden limitation — the CLI version still supports true blocking
human-in-the-loop input.

## Architecture

```
main.py                  CLI entry point
agent/
  worker.py               Core loop (Goal→Understand→Plan→Execute→Observe→Adapt→Verify→Complete)
  tool_registry.py         Tool schemas (Claude tool-use format) + dispatcher to real functions
tools/
  file_tools.py             search_inbox / read_document
  system_tools.py            enter_invoice_record / query_invoice_records / ask_user
environment/
  mock_inbox/                 Sample "emails" (text files) simulating invoices from 2 vendors
  internal_system.py          Mock internal ERP (JSON-backed record store)
```

**Planning is not a hardcoded pipeline.** At every step, the LLM (Claude) is
given the task, the full tool list, and the running transcript, and decides
the next action itself. The harness only executes whatever the model chooses
and feeds the real result back. This is what lets the same `worker.py`
handle the Company Y task above with zero code changes — the agent re-plans
from scratch based on what it actually finds.

**Reliability** is handled by surfacing failures to the model rather than
hiding them: `internal_system.enter_invoice` randomly simulates a transient
system timeout (~20% of calls) so the agent's retry logic is tested against a
real failure mode, not just a happy path. The model sees the error text and
decides whether to retry, try something else, or ask the user.

**Verification is structurally enforced**, not just prompted-for: the agent
is instructed it may only call `task_complete` after independently calling
`query_invoice_records` to confirm the entry actually exists with the correct
fields. It cannot simply trust the "success" response from the entry step.

**Human-in-the-loop**: `ask_user` is exposed as a real tool. If the agent
finds genuinely ambiguous state it can't resolve on its own, it pauses and
asks the user directly on the CLI, rather than guessing silently.

## What parts are genuinely autonomous

- **Planning**: the sequence of tool calls is decided by the model at runtime, not scripted. Swapping "Company X" for "Company Y" in the task requires no code change.
- **Extraction**: the model reads raw unstructured invoice text and extracts vendor/amount/due date itself — there is no regex-based field extraction in the pipeline for this.
- **Disambiguation**: when `search_inbox("Company X")` returns two invoices, the model has to reason about which one is "latest" from the dates itself.
- **Failure recovery**: when `enter_invoice_record` returns a simulated timeout, the model decides to retry rather than the harness retrying blindly.
- **Verification**: the model independently queries the internal system before declaring completion.

## What is currently hardcoded / manually configured

- The **environment itself** is simulated: the "inbox" is a folder of plain-text files instead of a real mailbox, and the "internal system" is a local JSON file instead of a real ERP/API. This was a deliberate scoping choice (see Assumptions) so the prototype could be narrow but genuinely working, per the problem statement's guidance.
- The **tool list** (`tool_registry.py`) is a fixed, hand-written set — the agent cannot discover or create new tools on its own; adding a new company workflow means adding a new tool function.
- The **retry budget** is implicit (max 12 planning steps total, not a dedicated per-tool retry counter) rather than a tuned backoff/retry policy.
- Invoice text format in the mock inbox is reasonably structured (labelled fields like "Amount Due:") — real emails/PDFs would be much messier, and extraction robustness on real documents is untested here.

## Models, frameworks, APIs, libraries used

- **Model**: Claude Sonnet 4.5 (`claude-sonnet-4-5`) via the Anthropic Python SDK, using native tool use (function calling) for planning.
- **Libraries**: `anthropic` (official SDK). No agent framework (e.g. LangChain/LangGraph) was used — the loop is written directly against the raw tool-use API so every part of the autonomy loop (planning, execution, verification gating) is explicit and inspectable rather than abstracted away by a framework, since the problem statement specifically asks us to justify these decisions.
- **AI coding tools used**: Claude (Anthropic) was used as a coding assistant while building this prototype.
- No pre-built agent templates or third-party agent frameworks were used.

## Biggest technical limitation

The agent currently operates on structured text files rather than real
documents or a real browser/application. It has not been tested against
messy real-world inputs (scanned PDFs, inconsistent email formats, actual
web UIs), where extraction and action-execution reliability would be
significantly harder than in this simulated environment. The simulated
20% random tool failure is also a simplistic stand-in for the much wider
variety of real failure modes (auth errors, rate limits, partial UI loads,
ambiguous page state) a real browser/desktop agent would hit.

## What I'd build next with 2 more weeks

1. **Real browser/document tools**: swap the mock inbox for actual email (IMAP/Gmail API) and PDF parsing, and add a real browser-automation tool (e.g. Playwright) so the agent operates on real pages instead of text files.
2. **Persistent company memory**: store learned facts across runs (e.g. "Company X's invoices always have a 20-day payment term") so the agent gets better at a specific company's workflows over time, not just within one task.
3. **A dedicated verifier step/model call** separate from the planner, so verification isn't just "the same model promises it checked" but a structurally separate critique pass.
4. **Per-tool retry/backoff policy** with a cap, instead of relying on the overall step budget.
5. **A small eval set** of 10-15 varied tasks (including deliberately ambiguous/adversarial ones) to measure autonomy and verification reliability quantitatively, not just anecdotally from one demo run.

## Assumptions made

- The "internal system" and "inbox" could be fully simulated/local rather than integrating with real third-party services, per the submission scope guidance ("You may restrict your prototype to a small environment, simulated company application...").
- A single example domain (invoice processing) was enough to demonstrate the general-purpose loop, rather than building shallow support for many different task types.
- No real company credentials or data were used — all invoice content is fabricated for this demo.
