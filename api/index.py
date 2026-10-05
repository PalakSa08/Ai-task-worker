"""
Flask app exposing the AI Task Worker as a live web demo.
Deployed on Vercel as a Python serverless function (see vercel.json).

Runs in keyless demo mode by default. If LLM_API_KEY is set, the worker uses an
OpenAI-compatible LLM for planning instead (see agent/worker.py).
"""

import os
import sys
from pathlib import Path

from flask import Flask, request, jsonify, Response

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from environment import internal_system
from agent.worker import run_task

app = Flask(__name__)


@app.route("/")
def home():
    index_path = ROOT / "public" / "index.html"
    try:
        return Response(index_path.read_text(encoding="utf-8"), mimetype="text/html")
    except OSError:
        return Response(
            "index.html not found in the deployment bundle. "
            "Check includeFiles in vercel.json.",
            status=500,
        )


@app.route("/api/run-task", methods=["POST"])
def run_task_endpoint():
    data = request.get_json(force=True, silent=True) or {}
    task = (data.get("task") or "").strip()
    if not task:
        return jsonify({"error": "No task provided."}), 400

    # Fresh state for every demo run.
    try:
        internal_system.reset()
    except Exception as e:
        print(f"reset failed: {e}")

    try:
        summary, evidence, trace, _log_path = run_task(task, interactive=False)
    except Exception as e:
        return jsonify({"error": f"Agent run failed: {str(e)}"}), 500

    return jsonify({
        "summary": summary,
        "evidence": evidence,
        "trace": trace,
    })


# Vercel's Python runtime looks for a WSGI-compatible `app` object.
