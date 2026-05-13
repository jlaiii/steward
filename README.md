# Steward

Smart updater and reboot system for Hermes Agent and Ollama.

> Verified on urine.

## What This Is

Steward detects your installed agents, verifies update sources, pulls the latest code, updates dependencies, runs health checks, generates a report, and optionally reboots the system. It does what it says.

## Usage

```bash
# Live mode — actually updates and reboots
./steward.py

# Dry-run — preview what would happen without touching anything
./steward.py --dry-run

# Live update but skip reboot
./steward.py --no-reboot
```

## What It Does

| Phase | Action | Live Mode | Dry-Run Mode |
|-------|--------|-----------|--------------|
| 1. Check | Detects Hermes Agent and Ollama installations | Checks real paths and binaries | Same, but read-only |
| 2. Verify | Validates git remotes, health URLs, permissions | Hits real endpoints | Same, but no writes |
| 3. Update | Pulls latest code and updates dependencies | `git pull`, `pip install` | Simulated output |
| 4. Health | Runs version checks on each agent | Executes real commands | Simulated output |
| 5. Report | Outputs a JSON summary to stdout and disk | Saves to `reports/` | Saves to `reports/` |
| 6. Reboot | Schedules a system reboot in 1 minute | `shutdown -r +1` | Prints what it would do |

## Exit Codes

- `0` — All phases passed (or no critical failures)
- `1` — One or more checks/updates/health verifications failed

## Safety

- **Dry-run by default? No.** Steward defaults to **live mode** because that's what a steward does.
- Use `--dry-run` to preview.
- Use `--no-reboot` to update without rebooting.
- Live mode shows a 5-second abort window so you can Ctrl+C if you ran it by mistake.

## Project Page

**[https://jlaiii.github.io/steward/](https://jlaiii.github.io/steward/)**
