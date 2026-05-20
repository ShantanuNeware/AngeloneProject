"""Approve orders helper.

Creates a `GO_LIVE` sentinel file in the workspace root with a short
confirmation message and timestamp. Intended as an explicit human approval
mechanism before running the engine with `--agent-approve`.

Usage:
  python tools/approve_orders.py --author Alice --message "Approved for live testing"
"""
import argparse
import os
from datetime import datetime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--author", required=True, help="Approver name")
    parser.add_argument("--message", default="GO LIVE", help="Approval message")
    parser.add_argument("--path", default=".", help="Workspace root path")
    args = parser.parse_args()

    filepath = os.path.join(args.path, "GO_LIVE")
    ts = datetime.utcnow().isoformat() + "Z"
    payload = {
        "author": args.author,
        "message": args.message,
        "timestamp": ts
    }

    with open(filepath, "w", encoding="utf-8") as fh:
        for k, v in payload.items():
            fh.write(f"{k}: {v}\n")

    print(f"Wrote GO_LIVE sentinel: {filepath}")


if __name__ == "__main__":
    main()
