"""Simple log monitor for the trading workspace.

Tails the most recent log file under `logs/` and writes any errors
to `logs/issues/issue_<ts>.log` for later inspection.

Usage: python tools/log_monitor.py --dir logs --poll 1
"""
import argparse
import os
import time
from datetime import datetime


KEYWORDS = ["✗ Analysis error", "ERROR -", "Traceback", "Exception"]


def find_latest_log_dir(logs_dir: str) -> str:
    if not os.path.isdir(logs_dir):
        raise FileNotFoundError(logs_dir)
    entries = [os.path.join(logs_dir, p) for p in os.listdir(logs_dir)]
    dirs = [p for p in entries if os.path.isdir(p)]
    if not dirs:
        return logs_dir
    dirs.sort(key=os.path.getmtime, reverse=True)
    return dirs[0]


def find_latest_log_file(log_dir: str) -> str:
    files = [os.path.join(log_dir, f) for f in os.listdir(log_dir) if os.path.isfile(os.path.join(log_dir, f))]
    if not files:
        raise FileNotFoundError(f"No log files in {log_dir}")
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def ensure_issues_dir(base_logs: str) -> str:
    issues = os.path.join(base_logs, "issues")
    os.makedirs(issues, exist_ok=True)
    return issues


def tail_file(path: str, poll: float = 1.0):
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        # Seek to end
        fh.seek(0, os.SEEK_END)
        while True:
            line = fh.readline()
            if not line:
                time.sleep(poll)
                continue
            yield line


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="logs", help="Top-level logs directory")
    parser.add_argument("--poll", type=float, default=1.0, help="Polling interval seconds")
    args = parser.parse_args()

    try:
        latest_dir = find_latest_log_dir(args.dir)
        latest_file = find_latest_log_file(latest_dir)
    except Exception as e:
        print("Log monitor error:", e)
        return

    print(f"Tailing: {latest_file}")
    issues_dir = ensure_issues_dir(args.dir)

    buffer = []
    for line in tail_file(latest_file, poll=args.poll):
        buffer.append(line)
        print(line, end="")
        for kw in KEYWORDS:
            if kw in line:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                out_path = os.path.join(issues_dir, f"issue_{ts}.log")
                # Write last ~200 lines for context
                with open(out_path, "w", encoding="utf-8") as outf:
                    outf.write("--- Captured by log_monitor.py ---\n")
                    outf.write(f"Source: {latest_file}\n")
                    outf.write(f"Detected: {kw}\n")
                    outf.write("--- Context ---\n")
                    outf.writelines(buffer[-200:])
                print(f"Wrote issue file: {out_path}")


if __name__ == "__main__":
    main()
