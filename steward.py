#!/usr/bin/env python3
"""
Steward — Smart Updater/Reboot System for Hermes Agent and Ollama
Checks, updates, verifies, and reboots. For real.
Verified on urine.
"""

import argparse
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

__version__ = "2.0.0"

REPORT_DIR = Path("reports")

CONFIG = {
    "agents": [
        {
            "name": "Hermes Agent",
            "paths": [
                Path.home() / ".hermes" / "hermes-agent",
            ],
            "git_remotes": [
                "https://github.com/NousResearch/hermes-agent.git",
            ],
            "health_urls": [
                "https://api.github.com/repos/NousResearch/hermes-agent/releases/latest"
            ],
            "update_cmd": "git pull --ff-only",
            "deps_cmd": "pip install -e . --upgrade",
            "health_cmd": "hermes --version",
        },
        {
            "name": "Ollama",
            "paths": [
                Path.home() / ".ollama",
                Path("/usr/local/bin/ollama"),
                Path("/usr/bin/ollama"),
            ],
            "git_remotes": [],
            "health_urls": [],
            "update_cmd": None,
            "deps_cmd": None,
            "health_cmd": "ollama --version",
        },
    ],
    "required_binaries": ["git", "python3"],
    "backup_paths": [Path.home() / ".hermes"],
}


@dataclass
class Step:
    phase: str
    name: str
    status: str
    details: str = ""
    duration_ms: int = 0


@dataclass
class Report:
    timestamp: str
    hostname: str
    os: str
    dry_run: bool
    overall_status: str
    steps: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def save_report(report: Report) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = report.timestamp.replace(":", "-")
    path = REPORT_DIR / f"report-{ts}.json"
    with open(path, "w") as f:
        json.dump(asdict(report), f, indent=2)
    return path


def print_banner(text: str):
    width = 64
    pad = (width - len(text) - 2) // 2
    print("\n" + "=" * width)
    print(" " * pad + text.upper() + " " * pad)
    print("=" * width)


def print_step(step: Step):
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "-", "INFO": "ℹ", "WARN": "⚠"}.get(
        step.status, "?"
    )
    print(f"  [{icon}] {step.phase:10} | {step.name:30} | {step.status}")
    if step.details:
        for line in step.details.splitlines():
            print(f"      {line}")


def run_cmd(cmd: str, cwd: Optional[Path] = None, timeout: int = 120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


def phase_check() -> list[Step]:
    print_banner("Phase 1: Check")
    steps = []
    for agent in CONFIG["agents"]:
        found = any(p.exists() for p in agent["paths"])
        details = [f"  {p} — {'EXISTS' if p.exists() else 'ABSENT'}" for p in agent["paths"]]
        steps.append(
            Step(
                phase="CHECK",
                name=f"Detect {agent['name']}",
                status="PASS" if found else "FAIL",
                details="\n".join(details),
            )
        )

    for binary in CONFIG["required_binaries"]:
        found = shutil.which(binary)
        steps.append(
            Step(
                phase="CHECK",
                name=f"Find binary: {binary}",
                status="PASS" if found else "FAIL",
                details=found or "Not found in PATH",
            )
        )
    return steps


def phase_verify() -> list[Step]:
    print_banner("Phase 2: Verify")
    steps = []

    for agent in CONFIG["agents"]:
        for remote in agent.get("git_remotes", []):
            rc, out, err = run_cmd(f"git ls-remote --heads {remote}", timeout=15)
            reachable = rc == 0
            detail = f"Exit code: {rc}"
            if err:
                detail += f" | {err[:80]}"
            steps.append(
                Step(
                    phase="VERIFY",
                    name=f"Reachable: {remote[:40]}...",
                    status="PASS" if reachable else "FAIL",
                    details=detail,
                )
            )

    for agent in CONFIG["agents"]:
        for url in agent.get("health_urls", []):
            ok = False
            detail = ""
            try:
                import urllib.request

                with urllib.request.urlopen(url, timeout=15) as resp:
                    ok = resp.status == 200
                    data = json.loads(resp.read())
                    detail = f"Status: {resp.status} | Latest: {data.get('tag_name', 'N/A')}"
            except Exception as e:
                detail = str(e)
            steps.append(
                Step(
                    phase="VERIFY",
                    name=f"Health check: {agent['name']}",
                    status="PASS" if ok else "FAIL",
                    details=detail,
                )
            )

    for bp in CONFIG["backup_paths"]:
        writable = os.access(bp.parent, os.W_OK)
        steps.append(
            Step(
                phase="VERIFY",
                name=f"Writable: {bp}",
                status="PASS" if writable else "FAIL",
                details="Directory writable" if writable else "Directory NOT writable",
            )
        )

    return steps


def phase_update(dry_run: bool) -> list[Step]:
    print_banner("Phase 3: Update")
    steps = []

    for agent in CONFIG["agents"]:
        found = any(p.exists() for p in agent["paths"])
        if not found:
            steps.append(
                Step(
                    phase="UPDATE",
                    name=f"Update {agent['name']}",
                    status="SKIP",
                    details="Agent not installed — skipping",
                )
            )
            continue

        # Find the git repo path (directory that exists)
        repo_path = None
        for p in agent["paths"]:
            if p.is_dir() and (p / ".git").exists():
                repo_path = p
                break
            elif p.is_dir():
                repo_path = p
                break

        if repo_path is None:
            steps.append(
                Step(
                    phase="UPDATE",
                    name=f"Update {agent['name']}",
                    status="SKIP",
                    details="No valid directory found",
                )
            )
            continue

        # Git pull
        update_cmd = agent.get("update_cmd")
        if update_cmd:
            if dry_run:
                steps.append(
                    Step(
                        phase="UPDATE",
                        name=f"git pull {agent['name']}",
                        status="INFO",
                        details=f"[DRY-RUN] Would run: {update_cmd} in {repo_path}",
                    )
                )
            else:
                rc, out, err = run_cmd(update_cmd, cwd=repo_path, timeout=60)
                success = rc == 0
                detail = out if out else err
                if "Already up to date" in out or "Already up-to-date" in out:
                    success = True
                    detail = "Already up to date"
                steps.append(
                    Step(
                        phase="UPDATE",
                        name=f"git pull {agent['name']}",
                        status="PASS" if success else "FAIL",
                        details=detail[:200],
                    )
                )
        else:
            steps.append(
                Step(
                    phase="UPDATE",
                    name=f"git pull {agent['name']}",
                    status="SKIP",
                    details="No update command configured",
                )
            )

        # Dependencies
        deps_cmd = agent.get("deps_cmd")
        if deps_cmd:
            if dry_run:
                steps.append(
                    Step(
                        phase="UPDATE",
                        name=f"deps {agent['name']}",
                        status="INFO",
                        details=f"[DRY-RUN] Would run: {deps_cmd} in {repo_path}",
                    )
                )
            else:
                rc, out, err = run_cmd(deps_cmd, cwd=repo_path, timeout=120)
                success = rc == 0
                detail = out if out else err
                steps.append(
                    Step(
                        phase="UPDATE",
                        name=f"deps {agent['name']}",
                        status="PASS" if success else "FAIL",
                        details=detail[:200],
                    )
                )
        else:
            steps.append(
                Step(
                    phase="UPDATE",
                    name=f"deps {agent['name']}",
                    status="SKIP",
                    details="No dependency command configured",
                )
            )

    return steps


def phase_health(dry_run: bool) -> list[Step]:
    print_banner("Phase 4: Health")
    steps = []

    for agent in CONFIG["agents"]:
        found = any(p.exists() for p in agent["paths"])
        if not found:
            steps.append(
                Step(
                    phase="HEALTH",
                    name=f"Health {agent['name']}",
                    status="SKIP",
                    details="Agent not installed",
                )
            )
            continue

        health_cmd = agent.get("health_cmd")
        if not health_cmd:
            steps.append(
                Step(
                    phase="HEALTH",
                    name=f"Health {agent['name']}",
                    status="SKIP",
                    details="No health command configured",
                )
            )
            continue

        if dry_run:
            steps.append(
                Step(
                    phase="HEALTH",
                    name=f"Health {agent['name']}",
                    status="INFO",
                    details=f"[DRY-RUN] Would run: {health_cmd}",
                )
            )
        else:
            rc, out, err = run_cmd(health_cmd, timeout=30)
            success = rc == 0
            detail = out if out else err
            steps.append(
                Step(
                    phase="HEALTH",
                    name=f"Health {agent['name']}",
                    status="PASS" if success else "FAIL",
                    details=detail[:200],
                )
            )

    return steps


def phase_report(all_steps: list[Step], dry_run: bool) -> tuple[list[Step], Path]:
    print_banner("Phase 5: Report")
    passes = sum(1 for s in all_steps if s.status == "PASS")
    fails = sum(1 for s in all_steps if s.status == "FAIL")
    skips = sum(1 for s in all_steps if s.status == "SKIP")
    infos = sum(1 for s in all_steps if s.status == "INFO")
    total = len(all_steps)

    report = Report(
        timestamp=datetime.datetime.now().isoformat(),
        hostname=platform.node(),
        os=f"{platform.system()} {platform.release()}",
        dry_run=dry_run,
        overall_status="HEALTHY" if fails == 0 else "ISSUES DETECTED",
        steps=[asdict(s) for s in all_steps],
        summary={
            "total_steps": total,
            "passed": passes,
            "failed": fails,
            "skipped": skips,
            "infos": infos,
            "dry_run": dry_run,
        },
    )

    path = save_report(report)
    print(f"\n  Report saved to: {path.resolve()}")

    steps = [
        Step(
            phase="REPORT",
            name="Generate JSON report",
            status="PASS",
            details=f"Steps: {total} | PASS {passes} | FAIL {fails} | SKIP {skips} | INFO {infos}",
        )
    ]
    return steps, path


def phase_reboot(dry_run: bool, no_reboot: bool) -> list[Step]:
    print_banner("Phase 6: Reboot")
    steps = []

    if no_reboot:
        steps.append(
            Step(
                phase="REBOOT",
                name="System reboot",
                status="SKIP",
                details="--no-reboot flag set. Skipping reboot.",
            )
        )
        return steps

    if dry_run:
        steps.append(
            Step(
                phase="REBOOT",
                name="System reboot",
                status="INFO",
                details="[DRY-RUN] Would run: shutdown -r +1 'Rebooting after Steward maintenance'",
            )
        )
        return steps

    # Actual reboot
    reboot_cmd = "shutdown -r +1 'Rebooting after Steward maintenance'"
    rc, out, err = run_cmd(reboot_cmd, timeout=10)
    if rc == 0 or rc == 64:  # 64 = macOS shutdown success
        steps.append(
            Step(
                phase="REBOOT",
                name="System reboot",
                status="PASS",
                details="Reboot scheduled in 1 minute. Run 'shutdown -c' to cancel.",
            )
        )
    else:
        # Try sudo
        rc2, out2, err2 = run_cmd(f"sudo {reboot_cmd}", timeout=10)
        if rc2 == 0:
            steps.append(
                Step(
                    phase="REBOOT",
                    name="System reboot",
                    status="PASS",
                    details="Reboot scheduled (via sudo) in 1 minute. Run 'sudo shutdown -c' to cancel.",
                )
            )
        else:
            steps.append(
                Step(
                    phase="REBOOT",
                    name="System reboot",
                    status="FAIL",
                    details=f"Failed to schedule reboot. Error: {err2 or err}",
                )
            )

    return steps


def main():
    parser = argparse.ArgumentParser(
        prog="steward",
        description="Smart updater and reboot system for Hermes Agent and Ollama.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate all actions without executing.",
    )
    parser.add_argument(
        "--no-reboot",
        action="store_true",
        help="Skip the reboot step even in live mode.",
    )
    args = parser.parse_args()

    dry_run = args.dry_run

    print_banner("steward")
    print(f"  Version:    {__version__}")
    print(f"  Mode:       {'DRY-RUN' if dry_run else 'LIVE'}")
    print(f"  Time:       {datetime.datetime.now().isoformat()}")
    print(f"  Host:       {platform.node()}")
    print(f"  OS:         {platform.system()} {platform.release()}")
    print(f"  User:       {os.environ.get('USER', os.environ.get('USERNAME', '?'))}")
    print(f"  PID:        {os.getpid()}")

    if not dry_run:
        print("\n  ⚠  LIVE MODE — This will actually update code and reboot the system.")
        print("  ⚠  Press Ctrl+C within 5 seconds to abort...")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n  Aborted by user.")
            sys.exit(0)

    all_steps: list[Step] = []
    all_steps.extend(phase_check())
    all_steps.extend(phase_verify())
    all_steps.extend(phase_update(dry_run))
    all_steps.extend(phase_health(dry_run))
    report_steps, report_path = phase_report(all_steps, dry_run)
    all_steps.extend(report_steps)
    all_steps.extend(phase_reboot(dry_run, args.no_reboot))

    print_banner("Summary")
    for s in all_steps:
        print_step(s)

    fails = sum(1 for s in all_steps if s.status == "FAIL")
    print(f"\n{'=' * 64}")
    print(f"  Overall: {'HEALTHY' if fails == 0 else 'ISSUES DETECTED'}")
    print(f"  Fails:   {fails}")
    print(f"  Report:  {report_path.resolve()}")
    print(f"{'=' * 64}\n")

    return 1 if fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
