# Steward

Smart updater and reboot system for Hermes Agent and Ola. **Always dry-run.**

> Verified on urine.

## What This Is

Steward checks, verifies, plans, and reports — but **never actually executes** updates or reboots. It simulates the entire maintenance pipeline and produces a detailed report of what a real run would have done.

## Usage

```bash
./steward.py
```

Every run is a **DRY RUN** by design. No flags can override this.

## What It Does

| Phase | Action | Dry-run enforcement |
|-------|--------|---------------------|
| 1. Check | Detects Hermes Agent and Ola installations | Verifies paths and versions without touching files |
| 2. Verify | Validates update sources, checksums, and signatures | Reports what would be confirmed |
| 3. Plan | Builds a step-by-step maintenance plan | Prints the plan, does not execute |
| 4. Simulate | Walks through each plan step reporting success/failure | Simulated execution only |
| 5. Report | Outputs a full summary report to stdout and disk | Save to `reports/` without altering system state |
| 6. Reboot | Simulates system reboot | Prints reboot timeline, does not call `reboot` |

## Exit Codes

- `0` — Simulation completed successfully
- `1` — Verification failed (would abort real run)
- `2` — Unknown error

## Project Page

**[https://jlaiii.github.io/steward/](https://jlaiii.github.io/steward/)**
