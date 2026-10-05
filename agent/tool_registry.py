"""
Central registry: defines the tools the planner (LLM) is allowed to choose from,
in the schema Claude's tool-use API expects, and dispatches a chosen tool call
to the real Python function that executes it.

This is the "reusable tool abstraction" the problem statement asks about:
adding a new company workflow mostly means adding a new entry here, not
rewriting the planning loop.
"""

from tools import file_tools, system_tools

TOOLS = [
    {
        "name": "search_inbox",
        "description": "Search the company inbox for documents (e.g. invoices) mentioning a given company/vendor name. Returns matching file names with their dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_name": {"type": "string", "description": "Name of the company/vendor to search for."}
            },
            "required": ["company_name"],
        },
    },
    {
        "name": "read_document",
        "description": "Read the full text content of a specific file found in the inbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string", "description": "Exact file name returned by search_inbox."}
            },
            "required": ["file_name"],
        },
    },
    {
        "name": "enter_invoice_record",
        "description": "Enter an extracted invoice into the internal company system. Call this only after extracting vendor, amount, and due_date from a document.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "amount": {"type": "string"},
                "due_date": {"type": "string"},
                "invoice_number": {"type": "string"},
            },
            "required": ["vendor", "amount", "due_date"],
        },
    },
    {
        "name": "query_invoice_records",
        "description": "Read-only lookup of invoice records already entered into the internal system, used to verify an entry was actually saved correctly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string", "description": "Optional vendor name to filter by."}
            },
        },
    },
    {
        "name": "ask_user",
        "description": "Ask the human user a clarifying question when the task is ambiguous or you cannot safely proceed (e.g. multiple conflicting matches found). Use sparingly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string"}
            },
            "required": ["question"],
        },
    },
    {
        "name": "task_complete",
        "description": "Call this ONLY after you have verified (via query_invoice_records) that the requested outcome was actually achieved. Provide a final summary and the evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "evidence": {"type": "string", "description": "Concrete evidence, e.g. the record ID and fields that were verified."},
            },
            "required": ["summary", "evidence"],
        },
    },
]

_DISPATCH = {
    "search_inbox": lambda **kw: file_tools.search_inbox(**kw),
    "read_document": lambda **kw: file_tools.read_document(**kw),
    "enter_invoice_record": lambda **kw: system_tools.enter_invoice_record(**kw),
    "query_invoice_records": lambda **kw: system_tools.query_invoice_records(**kw),
    "ask_user": lambda **kw: system_tools.ask_user(**kw),
}


def execute_tool(name: str, tool_input: dict, interactive: bool = True):
    if name == "task_complete":
        return {"status": "success", "note": "Completion acknowledged."}
    if name not in _DISPATCH:
        return {"status": "error", "error": f"Unknown tool '{name}'"}
    try:
        if name == "ask_user":
            return _DISPATCH[name](**tool_input, interactive=interactive)
        return _DISPATCH[name](**tool_input)
    except Exception as e:
        return {"status": "error", "error": str(e)}
