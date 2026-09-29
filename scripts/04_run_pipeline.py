#!/usr/bin/env python3
# =============================================================================
# Stage 4 - Run CI Pipelines
#
# Triggers GitHub Actions CI workflows for selected services.
# Each pipeline builds a Docker image, pushes it to ECR, and commits the new
# image tag back to the gitops repo so ArgoCD can pick it up.
#
# Requires: gh CLI (https://cli.github.com/) authenticated via 'gh auth login'
# Run from the root of the dpp-assignment3 directory.
# =============================================================================

import os
import subprocess
import sys
import time
from datetime import datetime

RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
BOLD   = "\033[1m"
NC     = "\033[0m"

def _ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):  print(f"{GREEN}[{_ts()}] OK  {msg}{NC}")
def warn(msg): print(f"{YELLOW}[{_ts()}] !!  {msg}{NC}")
def info(msg): print(f"{CYAN}[{_ts()}]    {msg}{NC}")
def die(msg):
    print(f"{RED}[{_ts()}] ERR {msg}{NC}", file=sys.stderr)
    sys.exit(1)

def run_cmd(args, ok_fail=False, capture=False):
    if capture:
        r = subprocess.run(args, capture_output=True, text=True)
        return r.stdout.strip(), r.returncode
    r = subprocess.run(args)
    if r.returncode != 0 and not ok_fail:
        die(f"Command failed: {' '.join(str(a) for a in args)}")
    return None, r.returncode

def prompt(var_name, label, example, default=""):
    current = os.environ.get(var_name, "")
    if current:
        info(f"Using {var_name}={current}  (pre-set in environment)")
        return current
    print()
    print(f"{CYAN}  {label}{NC}")
    print(f"    Example : {example}")
    if default:
        print(f"    Default : {default}")
        raw = input("    Your value [press Enter to use default]: ").strip()
    else:
        raw = input("    Your value: ").strip()
    value = raw if raw else default
    if not value:
        die(f"'{label}' is required.")
    log(f"  {var_name} = {value}")
    return value

# Service catalogue is built dynamically after collecting user inputs below.

# ---------------------------------------------------------------------------
# Verify gh CLI is installed and authenticated
# ---------------------------------------------------------------------------
print()
print("Checking required tools...")
if subprocess.run(["which", "gh"], capture_output=True).returncode != 0:
    die("gh CLI not found. Install from https://cli.github.com/ then run 'gh auth login'.")
auth_out, auth_rc = run_cmd(["gh", "auth", "status"], capture=True, ok_fail=True)
if auth_rc != 0:
    die("gh CLI is not authenticated. Run: gh auth login")
log("gh CLI found and authenticated.")

# ---------------------------------------------------------------------------
# Collect inputs
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  Zen Pharma -- CI Pipeline Trigger")
print("============================================")
print()
print("  This script triggers GitHub Actions CI pipelines for selected services.")
print("  Each pipeline: builds → scans → pushes image to ECR → updates gitops.")
print()

GITHUB_ORG     = prompt("GITHUB_ORG",        "GitHub username or org that owns the repos",
                        "<your-org>", "zenpharma")
FRONTEND_REPO  = prompt("FRONTEND_REPO",    "GitHub repo name for frontend",
                        "frontend", "frontend")
BACKEND_REPO   = prompt("BACKEND_REPO",     "GitHub repo name for backend",
                        "backend", "backend")
BRANCH         = prompt("BRANCH",           "Branch to build",
                        "develop", "develop")

# Update service catalogue with user-provided repo names
FRONTEND = [
    ("pharma-ui",             FRONTEND_REPO, "ci-pharma-ui.yml"),
]

BACKEND = [
    ("auth-service",          BACKEND_REPO,  "ci-auth-service.yml"),
    ("drug-catalog-service",  BACKEND_REPO,  "ci-drug-catalog.yml"),
    ("inventory-service",     BACKEND_REPO,  "ci-inventory-service.yml"),
    ("supplier-service",      BACKEND_REPO,  "ci-supplier-service.yml"),
    ("manufacturing-service", BACKEND_REPO,  "ci-manufacturing-service.yml"),
    ("notification-service",  BACKEND_REPO,  "ci-notification.yml"),
    ("qc-service",            BACKEND_REPO,  "ci-qc-service.yml"),
    ("api-gateway",           BACKEND_REPO,  "ci-api-gateway.yml"),
]

ALL_SERVICES = FRONTEND + BACKEND

# ---------------------------------------------------------------------------
# Service selection menu
# ---------------------------------------------------------------------------
print()
print(f"{BOLD}  Select which services to build:{NC}")
print()
print("    F) Frontend only")
print("       1) pharma-ui")
print()
print("    B) Backend only (all 8 services)")
print("       2) auth-service")
print("       3) drug-catalog-service")
print("       4) inventory-service")
print("       5) supplier-service")
print("       6) manufacturing-service")
print("       7) notification-service")
print("       8) qc-service")
print("       9) api-gateway")
print()
print("    A) All services (frontend + backend)")
print()
choice = input("    Your choice [F/B/A or 1-9]: ").strip().upper()

if choice == "F":
    selected = FRONTEND
elif choice == "B":
    selected = BACKEND
elif choice == "A":
    selected = ALL_SERVICES
elif choice.isdigit() and 1 <= int(choice) <= 9:
    selected = [ALL_SERVICES[int(choice) - 1]]
else:
    die(f"Invalid choice '{choice}'.")

print()
print("  Services to build:")
for name, repo, workflow in selected:
    print(f"    - {name}  ({GITHUB_ORG}/{repo} @ {BRANCH})")
print()
confirm = input("  Proceed? [Y/n]: ").strip() or "Y"
if confirm.upper() != "Y":
    print("Aborted.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Trigger workflows
# ---------------------------------------------------------------------------
triggered_runs = []  # (service_name, repo, workflow, run_id)

for name, repo, workflow in selected:
    full_repo = f"{GITHUB_ORG}/{repo}"
    print()
    print(f"--------------------------------------------")
    print(f"  Triggering: {name}")
    print(f"  Repo      : {full_repo}")
    print(f"  Workflow  : {workflow}  (branch: {BRANCH})")
    print(f"--------------------------------------------")

    _, rc = run_cmd(
        ["gh", "workflow", "run", workflow,
         "--repo", full_repo,
         "--ref", BRANCH],
        ok_fail=True,
    )
    if rc != 0:
        warn(f"Failed to trigger {name} — skipping. Check that workflow_dispatch is enabled.")
        continue

    # Give GitHub a moment to register the new run
    time.sleep(4)

    run_id_out, _ = run_cmd(
        ["gh", "run", "list",
         "--repo", full_repo,
         "--workflow", workflow,
         "--limit", "1",
         "--json", "databaseId",
         "--jq", ".[0].databaseId"],
        capture=True, ok_fail=True,
    )
    run_id = run_id_out.strip()
    if run_id:
        log(f"Triggered {name}: run #{run_id}  →  https://github.com/{full_repo}/actions/runs/{run_id}")
        triggered_runs.append((name, full_repo, workflow, run_id))
    else:
        warn(f"Triggered {name} but could not fetch run ID. Check GitHub Actions manually.")

if not triggered_runs:
    die("No workflows were triggered successfully.")

# ---------------------------------------------------------------------------
# Poll for completion
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  Waiting for pipeline(s) to complete...")
print("  (Ctrl+C to stop watching — pipelines continue running in GitHub)")
print("============================================")

POLL_INTERVAL = 30
MAX_WAIT      = 60 * 30  # 30 minutes

pending = list(triggered_runs)
results = {}
elapsed = 0

try:
    while pending and elapsed < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        still_pending = []
        for name, full_repo, workflow, run_id in pending:
            status_out, _ = run_cmd(
                ["gh", "run", "view", run_id,
                 "--repo", full_repo,
                 "--json", "status,conclusion",
                 "--jq", "[.status, .conclusion] | join(\"|\")",
                 ],
                capture=True, ok_fail=True,
            )
            parts    = status_out.split("|")
            status    = parts[0] if parts else "unknown"
            conclusion = parts[1] if len(parts) > 1 else ""

            if status == "completed":
                results[name] = conclusion
                if conclusion == "success":
                    log(f"{name}: {conclusion.upper()}")
                else:
                    warn(f"{name}: {conclusion.upper()}")
            else:
                info(f"{name}: {status}  ({elapsed}s elapsed)")
                still_pending.append((name, full_repo, workflow, run_id))

        pending = still_pending

except KeyboardInterrupt:
    print()
    warn("Stopped watching. Pipelines are still running in GitHub.")
    print()
    for name, full_repo, _, run_id in pending:
        print(f"  Watch: https://github.com/{full_repo}/actions/runs/{run_id}")
    sys.exit(0)

if pending:
    warn(f"Timed out after {MAX_WAIT}s. These pipelines are still running:")
    for name, full_repo, _, run_id in pending:
        print(f"    {name}: https://github.com/{full_repo}/actions/runs/{run_id}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  Pipeline Summary")
print("============================================")
failed = []
for name, conclusion in results.items():
    status_color = GREEN if conclusion == "success" else RED
    print(f"  {status_color}{name:<30} {conclusion.upper()}{NC}")
    if conclusion != "success":
        failed.append(name)

if failed:
    print()
    warn(f"{len(failed)} pipeline(s) failed: {', '.join(failed)}")
    warn("Fix the failures before running 05_deploy_services.py")
    sys.exit(1)

print()
log("All pipelines completed successfully.")
print()
print("  Images have been pushed to ECR and image tags updated in gitops.")
print()
print("Next step: python3 scripts/05_deploy_services.py")
