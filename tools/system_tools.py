"""
Tools exposing the mock internal system to the agent, and a human-in-the-loop
'ask_user' tool the agent can call when it cannot safely proceed on its own.
"""

import sys
from environment import internal_system


def enter_invoice_record(vendor: str, amount: str, due_date: str, invoice_number: str = None):
    return internal_system.enter_invoice(vendor, amount, due_date, invoice_number)


def query_invoice_records(vendor: str = None):
    return {"status": "success", "records": internal_system.query_invoices(vendor)}


def ask_user(question: str, interactive: bool = True):
    """
    Human-in-the-loop checkpoint.

    In the CLI (interactive=True), this pauses execution and asks the real
    user for input. In the stateless web demo (interactive=False), a live
    blocking prompt isn't possible within a single HTTP request, so the
    question is logged as a flag for the user to review instead -- the agent
    is told this and must decide how to proceed (e.g. make its best
    reasonable assumption and state it in the final summary) rather than
    hanging. In a production system this would route to a Slack/email
    approval step instead of either of these.
    """
    if interactive:
        print(f"\n[AGENT NEEDS INPUT] {question}")
        answer = input("Your answer: ")
        return {"status": "success", "answer": answer}
    else:
        return {
            "status": "deferred",
            "note": "Running in non-interactive (web demo) mode: no live human "
                     "is available to answer right now. Make your best reasonable "
                     "assumption, proceed, and clearly flag this assumption in "
                     "your final summary.",
            "question_logged": question,
        }
