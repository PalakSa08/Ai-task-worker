"""
Tools for interacting with the mock "inbox" environment (stand-in for a real mailbox,
shared drive, or document store). The agent never reads files directly — it must call
these tools, mirroring how a real AI employee would need to go through connectors.
"""

import os
import re
from pathlib import Path

INBOX_DIR = Path(__file__).parent.parent / "environment" / "mock_inbox"


def search_inbox(company_name: str):
    """
    Search the inbox for files whose content mentions the given company/vendor name.
    Returns a list of {file, date} so the agent can reason about which is "latest".
    """
    matches = []
    for fname in os.listdir(INBOX_DIR):
        fpath = INBOX_DIR / fname
        with open(fpath, "r") as f:
            content = f.read()
        if company_name.lower() in content.lower():
            date_match = re.search(r"Date:\s*([\d-]+)", content)
            date = date_match.group(1) if date_match else None
            matches.append({"file": fname, "date": date})
    return matches


def read_document(file_name: str):
    """Read the raw content of a specific file in the inbox."""
    fpath = INBOX_DIR / file_name
    if not fpath.exists():
        return {"status": "error", "error": f"File '{file_name}' not found in inbox."}
    with open(fpath, "r") as f:
        return {"status": "success", "content": f.read()}
