"""
CLI entry point for the AI Task Worker prototype.

Usage:
    export ANTHROPIC_API_KEY=sk-...
    python main.py "Find the latest invoice from Company X, extract the amount
    and due date, enter it into our internal system, and tell me once it is done."

Run environment/reset_demo.py beforehand (or pass --reset) to start from a clean
internal system state.
"""

import sys
import argparse

from environment import internal_system


def main():
    parser = argparse.ArgumentParser(description="Autonomous AI Task Worker prototype")
    parser.add_argument("task", type=str, help="Natural language task for the agent")
    parser.add_argument("--reset", action="store_true", help="Reset the mock internal system before running")
    args = parser.parse_args()

    if args.reset:
        internal_system.reset()
        print("[setup] Internal system reset to empty state.\n")

    from agent.worker import run_task

    print(f"=== Starting AI Task Worker ===\nTask: {args.task}\n")
    summary, evidence, trace, log_path = run_task(args.task)

    print("\n=== FINAL RESULT ===")
    print(f"Summary : {summary}")
    print(f"Evidence: {evidence}")
    print(f"Full trace saved to: {log_path}")


if __name__ == "__main__":
    main()
