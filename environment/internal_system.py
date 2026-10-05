"""
Mock internal company system (stand-in for a real ERP / accounting tool).

This simulates the kind of internal system an AI employee would need to operate:
a simple record store with CRUD operations, accessed only through defined
functions (never direct file access) so the agent must go through "tools",
just like it would with a real internal system's API or UI.
"""

import json
import os
import time
import random
from pathlib import Path

# Vercel's project folder is read-only; only /tmp is writable there.
if os.environ.get("VERCEL"):
    DB_PATH = Path("/tmp/internal_system_data.json")
else:
    DB_PATH = Path(__file__).parent / "internal_system_data.json"


def _load():
    if not DB_PATH.exists():
        return {"invoices": []}
    with open(DB_PATH, "r") as f:
        return json.load(f)


def _save(data):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=2)


def reset():
    """Reset the mock system to empty state. Used before each fresh run/demo."""
    _save({"invoices": []})


def enter_invoice(vendor: str, amount: str, due_date: str, invoice_number: str = None,
                   simulate_transient_failure: bool = True):
    """
    Simulates entering an invoice record into the internal system.

    simulate_transient_failure: with a small probability, simulates a transient
    system error (e.g. API timeout) so the agent's retry/recovery logic has
    something real to handle, instead of everything always succeeding.
    """
    if simulate_transient_failure and random.random() < 0.2:
        return {"status": "error", "error": "System timeout: internal system did not respond. Try again."}

    data = _load()
    record = {
        "id": f"REC-{int(time.time() * 1000) % 100000}",
        "vendor": vendor,
        "amount": amount,
        "due_date": due_date,
        "invoice_number": invoice_number,
        "entered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    data["invoices"].append(record)
    _save(data)
    return {"status": "success", "record": record}


def query_invoices(vendor: str = None):
    """Read-only lookup, used by the agent's verifier to independently confirm an entry exists."""
    data = _load()
    if vendor is None:
        return data["invoices"]
    return [r for r in data["invoices"] if vendor.lower() in r["vendor"].lower()]
