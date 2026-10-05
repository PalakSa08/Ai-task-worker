"""
Flask app exposing the AI Task Worker as a live web demo.
Deployed on Vercel as a Python serverless function (see vercel.json).

Note: the mock internal system is file-based (environment/internal_system_data.json).
On Vercel's serverless filesystem this resets on every cold start, which is fine
for a stateless demo -- each run starts clean, which is actually the behaviour
we want for a public demo anyone can try repeatedly.
"""

import os
import sys
import json
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

sys.path.insert(0, str(Path(__file__).parent.parent))

from environment import internal_system
from agent.worker import run_task

app = Flask(__name__, static_folder="../public", static_url_path="")


@app.route("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/run-task", methods=["POST"])
def run_task_endpoint():
    data = request.get_json(force=True)
    task = (data or {}).get("task", "").strip()
    if not task:
        return jsonify({"error": "No task provided."}), 400

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "Server is missing ANTHROPIC_API_KEY."}), 500

    # Fresh state for every demo run.
    internal_system.reset()

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
