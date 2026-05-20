# Agent runbook — Realtime monitor & cautious order placement

# description: Senior Quantitative Trading Architect & Python Refactoring Expert - Specializes in clean architecture, event-driven trading systems, market regime detection, and scalable algorithmic trading platforms

Purpose
- Run the trading system in realtime when market is live.
- Monitor logs, detect and fix runtime issues where safe, and iterate until the project is stable.
- Be deliberately cautious about placing live orders: default to dry-run and require explicit operator confirmation before any real orders.

Prerequisites
- Ensure config has API keys and credentials in `config/` and secrets are not committed.
- Run on the approved machine only. Keep backups of `logs/` and `heartbeat.json`.

Operation modes (priority order)
- monitor (default): only observe market, tail logs, collect diagnostics, do not simulate trades.
- dry-run: run strategy code and simulate orders (recommended for continuous operation).
- live: allow real orders — ONLY enabled after explicit confirmation (see Safety below).

How to run
- PowerShell monitor-only (recommended first):

  powershell
  python tradingsystem/main_refactored.py --agent-mode monitor

- Dry-run (simulate orders):

  python tradingsystem/main_refactored.py --agent-mode dry-run

- Live (explicit confirmation required):
  - Method A (flag + confirm file): set `--agent-mode live --confirm-file ./GO_LIVE` and create the empty file `GO_LIVE` when you are present and accept risk.
  - Method B (env + manual flag): set environment variable `CONFIRM_ORDERS=1` and run with `--agent-approve`.

Safety & confirmation rules (must be enforced by operator scripts)
- Default behavior: `dry-run`. The agent must never place real orders unless one of the explicit confirmation methods is present.
- The agent must require a human-readable confirmation before placing the first live order in a session: either
  1) presence of the sentinel file `GO_LIVE` in workspace root, AND a short human confirmation message written to `logs/GO_LIVE_CONFIRM.txt`; OR
  2) operator runs a separate one-time command `python tools/approve_orders.py --session <id>` (not provided by agent unless implemented).
- If `GO_LIVE` is removed or `CONFIRM_ORDERS` unset, the agent must switch back to `dry-run` and stop new live orders.

Log monitoring
- Primary logs: `logs/` (subfolders by date). Use PowerShell tailing:

  Get-Content .\logs\2026-05-11\*.log -Wait -Tail 50

- Or use a small Python monitor to parse logs and surface errors to the operator (`tools/log_monitor.py` — optional).

Auto-diagnostics & safe fixes (agent behavior)
- On recoverable exceptions (ImportError, transient network errors, websocket disconnects):
  - collect stack trace and last 200 log lines, write to `logs/last_error_<ts>.log`.
  - attempt a single safe action: restart the failed component/process (via configured supervisor), or re-init a connection.
  - if the same failure repeats within N attempts (configurable, default 3), stop automated restarts and escalate.
- On unknown or potentially dangerous conditions (unexpected account changes, unauthorized balance drift, suspicious trade fills):
  - Immediately stop attempts to place any order, switch to `monitor` mode, and notify the operator by writing `logs/ALERT_<ts>.md` with details.

Issue tracking & iteration
- When an error cannot be auto-fixed, create a minimal issue file in `logs/issues/` with reproducible steps and context.
- The agent will attempt simple code fixes only when they are unambiguous (e.g., missing dependency: suggest `pip install <pkg>`). All code patches must be approved by the operator before being applied.

Minimal recommended additions (operator actions)
- Add a small `tools/log_monitor.py` to parse and summarize errors (I can help scaffold this).
- Add a simple `tools/approve_orders.py` utility that writes/verifies the `GO_LIVE` sentinel and a short confirmation message.
- Use a process supervisor (systemd, NSSM on Windows, or a simple wrapper `run_supervised.ps1`) to auto-restart the `main_refactored.py` process when it exits.

Telemetry & heartbeat
- Keep `heartbeat.json` updated with agent state (mode, last_error, uptime). The agent should write state every 30 seconds.

Operator guidelines
- Start in `monitor` for at least one full market open cycle to verify signals and logs.
- Move to `dry-run` to validate simulated order flow and error handling.
- Only enable `live` when you are present, have confirmed the sentinel, and have reviewed recent logs and risk settings.

Safety-first rule (non-negotiable)
- If any automated action would create or modify order placement code or send a real order, the agent MUST require a human confirmation step described above before performing it.

Contact / next steps
- If you want, I can:
  - scaffold `tools/log_monitor.py` and `tools/approve_orders.py` next,
  - implement a minimal supervised runner for Windows PowerShell,
  - or wire the `CONFIRM_ORDERS` sentinel into `main_refactored.py` so it enforces the rules.

---
Generated by the workspace agent runbook generator; keep this file under version control and update as procedures evolve.
