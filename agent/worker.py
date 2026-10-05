"""
Core autonomous loop: Goal -> Understand -> Plan -> Execute -> Observe -> Adapt -> Verify -> Complete.

Design choice: planning is NOT a hardcoded pipeline (search -> read -> extract -> enter).
Instead, at every step, the LLM is given the goal, full tool list, and the running
transcript of what has happened so far, and must itself decide the next action.
This is what makes the system generalize to tasks other than the invoice example
without any code changes to this file.

Reliability is handled at the harness level: failed tool calls are fed back to the
model as observations (not hidden), so the model can decide to retry, try an
alternative, or ask the user -- rather than the harness silently retrying blindly.

Verification is enforced structurally: the model is instructed it may only call
task_complete after it has independently queried the internal system to confirm
the record exists with the correct fields. This prevents the agent from just
*claiming* success.
"""

import os
import json
import time
from pathlib import Path

import anthropic

from agent.tool_registry import TOOLS, execute_tool

MODEL = "claude-sonnet-4-5"
MAX_STEPS = 12
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
"""


def _log(entries, task):
    LOG_DIR.mkdir(exist_ok=True)
    fname = LOG_DIR / f"run_{int(time.time())}.json"
    with open(fname, "w") as f:
        json.dump({"task": task, "trace": entries}, f, indent=2)
    return fname


def run_task(task: str, api_key: str = None, interactive: bool = True):
    """
    Runs the full autonomous loop for a single natural-language task.
    Returns (final_summary, evidence, trace, log_file_path).

    interactive=False is used by the stateless web demo, where ask_user cannot
    block on real input (see tools/system_tools.py for how that's handled).
    """
    client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    messages = [{"role": "user", "content": f"Task: {task}"}]
    trace = []

    for step in range(MAX_STEPS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Record any reasoning text the model produced this step
        text_parts = [b.text for b in response.content if b.type == "text"]
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        messages.append({"role": "assistant", "content": response.content})

        if text_parts:
            trace.append({"step": step, "type": "reasoning", "content": " ".join(text_parts)})
            print(f"\n[STEP {step}] Reasoning: {' '.join(text_parts)[:400]}")

        if not tool_use_blocks:
            # Model stopped without calling a tool -- treat as done/stuck.
            break

        tool_results = []
        done = False
        final_summary, final_evidence = None, None

        for block in tool_use_blocks:
            print(f"[STEP {step}] Action: {block.name}({block.input})")
            result = execute_tool(block.name, block.input, interactive=interactive)
            print(f"[STEP {step}] Observation: {json.dumps(result)[:300]}")

            trace.append({
                "step": step,
                "type": "action",
                "tool": block.name,
                "input": block.input,
                "result": result,
            })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result),
            })

            if block.name == "task_complete":
                done = True
                final_summary = block.input.get("summary")
                final_evidence = block.input.get("evidence")

        messages.append({"role": "user", "content": tool_results})

        if done:
            log_path = _log(trace, task)
            return final_summary, final_evidence, trace, log_path

    log_path = _log(trace, task)
    return (
        "Agent did not reach a verified completion within the step budget.",
        "No verified evidence produced.",
        trace,
        log_path,
    )
