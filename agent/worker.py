"""
Core worker loop: Goal -> Understand -> Plan -> Execute -> Observe -> Adapt -> Verify -> Complete.

Two modes, chosen automatically:

1. LLM mode (if LLM_API_KEY is set): an OpenAI-compatible model (Groq, Gemini,
   OpenRouter...) plans every step itself via tool calling.
2. Keyless demo mode (no key needed): a deterministic, rule-based worker runs the
   same tools in a fixed order with retry + verification. This is NOT LLM
   planning -- it exists so the hosted demo works with zero keys or credits.

Both modes return (final_summary, evidence, trace, log_file_path), so api/index.py
and main.py work unchanged.
"""

import os
import re
import json
import time
from datetime import datetime
from pathlib import Path

from agent.tool_registry import TOOLS, execute_tool

MODEL = os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile")
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
MAX_STEPS = 12

# Vercel's filesystem is read-only except /tmp
if os.environ.get("VERCEL"):
    LOG_DIR = Path("/tmp/logs")
else:
    LOG_DIR = Path(__file__).parent.parent / "logs"

SYSTEM_PROMPT = """You are an autonomous AI worker operating inside a company environment.

You are given a natural-language task from a user. You do NOT get a predefined
sequence of steps -- you must figure out what needs to be done and in what order,
using only the tools available to you.

Rules you must follow:
1. Break the task into the actions actually required; do not assume steps that
   weren't asked for.
2. If a tool call fails or returns an error, read the error and decide a sensible
   next step (retry, try a different approach, or ask the user) -- do not repeat
   the exact same failing call blindly more than once.
3. If you find information that is ambiguous or conflicting (e.g. more than one
   plausible match for "the latest invoice"), reason about it yourself first
   (e.g. compare dates) and only use ask_user if you genuinely cannot resolve it.
4. You must independently VERIFY the outcome by calling query_invoice_records
   before calling task_complete. Do not call task_complete based only on an
   enter_invoice_record success response -- confirm the record is actually
   retrievable and correct.
5. Call task_complete only once, as your final action, with a concise summary
   and concrete evidence (record id, fields).
6. Be efficient: do not call tools you don't need.
7. Call one tool at a time and wait for its result before the next call.
"""


def _log(entries, task):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        fname = LOG_DIR / f"run_{int(time.time())}.json"
        with open(fname, "w") as f:
            json.dump({"task": task, "trace": entries}, f, indent=2)
        return fname
    except OSError:
        return None  # never let logging crash a run


# --------------------------------------------------------------------------
# Mode 2: keyless rule-based worker
# --------------------------------------------------------------------------

def _doc_text(result):
    """Pull the document text out of whatever read_document returned."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        strings = [v for v in result.values() if isinstance(v, str)]
        if strings:
            return max(strings, key=len)
    return json.dumps(result)


def _parse_fields(text):
    """Extract labelled fields like 'Amount Due: $1,200' line by line."""
    fields = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if not value:
            continue
        if key in ("amount due", "amount", "total", "total due"):
            fields.setdefault("amount", value)
        elif key in ("due date", "payment due", "due"):
            fields.setdefault("due_date", value)
        elif key in ("invoice number", "invoice no", "invoice no.", "invoice #", "invoice id"):
            fields.setdefault("invoice_number", value)
        elif key in ("date", "invoice date", "issue date", "issued"):
            fields.setdefault("date", value)
        elif key in ("vendor", "from", "company"):
            fields.setdefault("vendor", value)
    return fields


def _to_date(s):
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime((s or "").strip(), fmt)
        except ValueError:
            continue
    return datetime.min


def _extract_company(task):
    m = re.search(r"(?:from|by|for)\s+((?:company\s+)?[A-Z][\w&.\- ]*?)(?:[,.]|\s+and\b|\s+extract|\s+enter|$)", task)
    if m:
        return m.group(1).strip()
    m = re.search(r"company\s+\w+", task, re.I)
    return m.group(0) if m else None


def _run_keyless(task, interactive):
    trace = []
    step = 0

    def act(tool, **kwargs):
        nonlocal step
        result = execute_tool(tool, kwargs, interactive=interactive)
        trace.append({"step": step, "type": "action", "tool": tool, "input": kwargs, "result": result})
        print(f"[STEP {step}] {tool}({kwargs}) -> {json.dumps(result)[:200]}")
        step += 1
        return result

    def think(text):
        trace.append({"step": step, "type": "reasoning", "content": text})
        print(f"[STEP {step}] {text}")

    def fail(msg):
        return msg, "No verified evidence produced.", trace, _log(trace, task)

    think("Keyless demo mode: running the rule-based worker (no LLM).")

    company = _extract_company(task)
    if not company:
        return fail("Could not identify a company name in the task.")
    think(f"Understood goal: process the latest invoice from '{company}'.")

    # 1. Search
    found = act("search_inbox", company_name=company)
    files = list(dict.fromkeys(re.findall(r"[\w\-. ]+?\.(?:txt|md|eml)", json.dumps(found))))
    files = [f.strip() for f in files]
    if not files:
        return fail(f"No documents found in the inbox for '{company}'.")

    # 2. Read every match and pick the latest by date
    docs = []
    for fn in files:
        text = _doc_text(act("read_document", file_name=fn))
        fields = _parse_fields(text)
        docs.append((_to_date(fields.get("date")), fn, fields))
    docs.sort(key=lambda d: d[0])
    _, chosen, fields = docs[-1]
    if len(docs) > 1:
        think(f"{len(docs)} invoices matched; picked the most recent by date: {chosen}.")

    if "amount" not in fields or "due_date" not in fields:
        return fail(f"Could not extract amount/due date from {chosen}.")

    entry = {
        "vendor": fields.get("vendor", company),
        "amount": fields["amount"],
        "due_date": fields["due_date"],
    }
    if "invoice_number" in fields:
        entry["invoice_number"] = fields["invoice_number"]
    think(f"Extracted fields: {entry}")

    # 3. Enter, retrying on transient failures
    entered = False
    for attempt in range(1, 5):
        result = act("enter_invoice_record", **entry)
        if isinstance(result, dict) and result.get("status") == "error":
            think(f"Entry failed (attempt {attempt}): {result.get('error')}. Retrying.")
            continue
        entered = True
        break
    if not entered:
        return fail("Could not enter the invoice after 4 attempts.")

    # 4. Verify independently
    check = act("query_invoice_records", vendor=entry["vendor"])
    blob = json.dumps(check)
    amount_digits = re.sub(r"[^\d.]", "", entry["amount"])
    if entry["due_date"] not in blob or amount_digits not in re.sub(r"[^\d.]", "", blob):
        return fail("Verification failed: the record was not found with the expected fields.")
    think("Verified: record exists in the internal system with the correct fields.")

    # 5. Complete
    summary = (
        f"Entered the latest invoice from {entry['vendor']} "
        f"(amount {entry['amount']}, due {entry['due_date']}) and verified it."
    )
    evidence = f"Source: {chosen}. Fields: {entry}. Confirmed via query_invoice_records."
    act("task_complete", summary=summary, evidence=evidence)
    return summary, evidence, trace, _log(trace, task)


# --------------------------------------------------------------------------
# Mode 1: LLM-planned worker (OpenAI-compatible providers)
# --------------------------------------------------------------------------

def _openai_tools(tools):
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
        for t in tools
    ]


def _run_llm(task, api_key, interactive):
    from openai import OpenAI  # imported lazily so keyless mode needs no openai package

    client = OpenAI(api_key=api_key, base_url=BASE_URL)
    tools = _openai_tools(TOOLS)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Task: {task}"},
    ]
    trace = []

    for step in range(MAX_STEPS):
        try:
            response = client.chat.completions.create(
                model=MODEL, messages=messages, tools=tools,
                tool_choice="auto", max_tokens=1024, temperature=0,
            )
        except Exception as e:
            trace.append({"step": step, "type": "llm_error", "content": str(e)[:500]})
            print(f"\n[STEP {step}] LLM error: {str(e)[:300]}")
            messages.append({"role": "user", "content":
                "Your last response could not be processed. Call exactly one valid tool with valid JSON arguments."})
            continue

        msg = response.choices[0].message
        tool_calls = msg.tool_calls or []

        turn = {"role": "assistant", "content": msg.content or ""}
        if tool_calls:
            turn["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                for tc in tool_calls
            ]
        messages.append(turn)

        if msg.content:
            trace.append({"step": step, "type": "reasoning", "content": msg.content})
            print(f"\n[STEP {step}] Reasoning: {msg.content[:400]}")

        if not tool_calls:
            break

        done, final_summary, final_evidence = False, None, None
        for tc in tool_calls:
            name = tc.function.name
            try:
                tool_input = json.loads(tc.function.arguments or "{}")
                result = execute_tool(name, tool_input, interactive=interactive)
            except json.JSONDecodeError:
                tool_input = {}
                result = {"status": "error", "error": "Tool arguments were not valid JSON."}
            print(f"[STEP {step}] Action: {name}({tool_input}) -> {json.dumps(result)[:300]}")

            trace.append({"step": step, "type": "action", "tool": name, "input": tool_input, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

            if name == "task_complete":
                done = True
                final_summary = tool_input.get("summary")
                final_evidence = tool_input.get("evidence")

        if done:
            return final_summary, final_evidence, trace, _log(trace, task)

    return (
        "Agent did not reach a verified completion within the step budget.",
        "No verified evidence produced.",
        trace,
        _log(trace, task),
    )


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def run_task(task: str, api_key: str = None, interactive: bool = True):
    key = os.environ.get("LLM_API_KEY") or api_key
    # Ignore a leftover Anthropic key: it won't work with the OpenAI-compatible client.
    if key and key == os.environ.get("ANTHROPIC_API_KEY"):
        key = None
    if key:
        return _run_llm(task, key, interactive)
    return _run_keyless(task, interactive)
