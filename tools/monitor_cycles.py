"""Monitor `heartbeat.json` and stop when a target number of cycles complete.

Writes a report to `logs/issues/monitor_report_<ts>.json` when done.

Usage:
  python tools/monitor_cycles.py --count 20 --interval 10
"""
import argparse
import json
import os
import time
from datetime import datetime


def read_heartbeat(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ensure_issues_dir() -> str:
    issues = os.path.join(os.getcwd(), "logs", "issues")
    os.makedirs(issues, exist_ok=True)
    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20, help="Number of cycles to wait")
    parser.add_argument("--interval", type=int, default=10, help="Poll interval in seconds")
    parser.add_argument("--heartbeat", default="heartbeat.json", help="Path to heartbeat.json")
    parser.add_argument("--out", default=None, help="Path to output report file")
    args = parser.parse_args()

    hb_path = args.heartbeat
    if not os.path.isabs(hb_path):
        hb_path = os.path.join(os.getcwd(), hb_path)

    if not os.path.exists(hb_path):
        print(f"heartbeat file not found: {hb_path}")
        raise SystemExit(2)

    hb = read_heartbeat(hb_path)
    start_cycle = int(hb.get("cycle_count", 0))
    target = start_cycle + int(args.count)
    start_time = datetime.utcnow()

    issues_dir = ensure_issues_dir()
    out_file = args.out or os.path.join(issues_dir, f"monitor_report_{start_time.strftime('%Y%m%d_%H%M%S')}.json")

    print(f"Monitoring heartbeat: start_cycle={start_cycle}, target={target}")

    last_seen = start_cycle
    while True:
        try:
            hb = read_heartbeat(hb_path)
        except Exception as exc:
            print("Error reading heartbeat:", exc)
            time.sleep(args.interval)
            continue

        current = int(hb.get("cycle_count", 0))
        now = datetime.utcnow().isoformat() + "Z"
        print(f"[{now}] cycle={current} / target={target}")

        if current >= target:
            end_time = datetime.utcnow()
            report = {
                "start_cycle": start_cycle,
                "end_cycle": current,
                "cycles_elapsed": current - start_cycle,
                "start_time": start_time.isoformat() + "Z",
                "end_time": end_time.isoformat() + "Z",
                "duration_seconds": int((end_time - start_time).total_seconds()),
                "heartbeat_snapshot": hb,
            }
            with open(out_file, "w", encoding="utf-8") as outf:
                json.dump(report, outf, indent=2)
            print("Target reached; wrote report:", out_file)
            break

        last_seen = current
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
