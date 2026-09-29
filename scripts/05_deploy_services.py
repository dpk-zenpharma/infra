#!/usr/bin/env python3
# =============================================================================
# Stage 5 - Deploy Services
#
# Applies ArgoCD Application manifests for selected services so ArgoCD starts
# syncing them to the cluster. Run after 04_run_pipeline.py has built images
# and updated the image tags in the gitops repo.
#
# Run from anywhere — paths are resolved relative to this script's location.
# =============================================================================

import os
import subprocess
import sys
import time
from datetime import datetime

# Default project root is two levels above this script (infra/scripts/ → project root)
DEFAULT_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

def prompt_choice(var_name, label, choices):
    current = os.environ.get(var_name, "")
    if current:
        info(f"Using {var_name}={current}  (pre-set in environment)")
        return current
    print()
    print(f"{CYAN}  {label}{NC}")
    for i, c in enumerate(choices, 1):
        print(f"    {i}) {c}")
    raw = input("    Enter number [1]: ").strip() or "1"
    try:
        idx = int(raw) - 1
        assert 0 <= idx < len(choices)
    except (ValueError, AssertionError):
        die(f"Invalid choice '{raw}'.")
    value = choices[idx]
    log(f"  {var_name} = {value}")
    return value

def kubectl_apply_yaml(yaml_str):
    r = subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml_str, text=True)
    if r.returncode != 0:
        die("kubectl apply failed.")

# ---------------------------------------------------------------------------
# Service catalogue
# (display_name, app_yaml_filename)
# Order matters: dependencies must be deployed before dependents.
# ---------------------------------------------------------------------------
FRONTEND_SERVICES = [
    ("pharma-ui",             "pharma-ui-app.yaml"),
]

BACKEND_SERVICES = [
    ("auth-service",          "auth-service-app.yaml"),
    ("drug-catalog-service",  "catalog-service-app.yaml"),
    ("inventory-service",     "inventory-service-app.yaml"),
    ("supplier-service",      "supplier-service-app.yaml"),
    ("manufacturing-service", "manufacturing-service-app.yaml"),
    ("notification-service",  "notification-service-app.yaml"),
    ("qc-service",            "qc-service-app.yaml"),
    ("api-gateway",           "api-gateway-app.yaml"),
]

ALL_SERVICES = FRONTEND_SERVICES + BACKEND_SERVICES  # frontend first (matches menu numbering)

# ---------------------------------------------------------------------------
# Verify tools
# ---------------------------------------------------------------------------
print()
print("Checking required tools...")
if subprocess.run(["which", "kubectl"], capture_output=True).returncode != 0:
    die("kubectl not found.")
log("kubectl found.")

# ---------------------------------------------------------------------------
# Collect inputs
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  Zen Pharma -- Deploy Services")
print("============================================")
print()
print("  This script applies ArgoCD Application manifests so ArgoCD starts")
print("  syncing selected services to your EKS cluster.")
print()
print("  Prerequisites:")
print("    - Script 02 completed (ArgoCD repo + AppProject configured)")
print("    - Script 03 completed (secrets synced to the namespace)")
print("    - Script 04 completed (images built and pushed to ECR)")
print()

ENV            = prompt_choice("ENV", "Target environment", ["dev", "qa", "prod"])

print(f"\n{CYAN}  NOTE: Enter your personal GitHub username, not the organization name.")
print(f"        This is used to replace placeholders in ArgoCD Application manifests.{NC}\n")

GITHUB_USERNAME = prompt("GITHUB_USERNAME", "Your personal GitHub username",
                         "<your-github-username>", "ravdsun")

default_gitops = os.path.join(DEFAULT_PROJECT_ROOT, "gitops")
GITOPS_PATH     = prompt("GITOPS_PATH", "Local path to your gitops repo",
                         default_gitops, default_gitops)

APPS_DIR = os.path.join(GITOPS_PATH, "argocd/apps", ENV)
if not os.path.isdir(APPS_DIR):
    die(f"Apps directory not found: {APPS_DIR}")

# ---------------------------------------------------------------------------
# Service selection menu
# ---------------------------------------------------------------------------
print()
print(f"{BOLD}  Select which services to deploy to '{ENV}':{NC}")
print()
print("    F) Frontend only")
print("       1) pharma-ui")
print()
print("    B) All backend services")
print("       2) auth-service")
print("       3) drug-catalog-service")
print("       4) inventory-service")
print("       5) supplier-service")
print("       6) manufacturing-service")
print("       7) notification-service")
print("       8) qc-service")
print("       9) api-gateway")
print()
print("    A) All services  (backend first, then frontend)")
print()
choice = input("    Your choice [F/B/A or 1-9]: ").strip().upper()

if choice == "F":
    selected = FRONTEND_SERVICES
elif choice == "B":
    selected = BACKEND_SERVICES
elif choice == "A":
    selected = ALL_SERVICES
elif choice.isdigit() and 1 <= int(choice) <= 9:
    selected = [ALL_SERVICES[int(choice) - 1]]
else:
    die(f"Invalid choice '{choice}'.")

print()
print(f"  Services to deploy → namespace '{ENV}':")
for name, yaml_file in selected:
    yaml_path = os.path.join(APPS_DIR, yaml_file)
    exists    = "✓" if os.path.isfile(yaml_path) else "✗ MISSING"
    print(f"    {exists}  {name}  ({yaml_file})")
print()
confirm = input("  Proceed? [Y/n]: ").strip() or "Y"
if confirm.upper() != "Y":
    print("Aborted.")
    sys.exit(0)

# ---------------------------------------------------------------------------
# Apply ArgoCD Application manifests
# ---------------------------------------------------------------------------
print()
applied = []
skipped = []

for name, yaml_file in selected:
    yaml_path = os.path.join(APPS_DIR, yaml_file)
    print(f"--------------------------------------------")
    print(f"  Deploying: {name}")
    print(f"--------------------------------------------")

    if not os.path.isfile(yaml_path):
        warn(f"  Manifest not found: {yaml_path} — skipping.")
        skipped.append(name)
        continue

    with open(yaml_path) as f:
        content = f.read().replace("your-github-username", GITHUB_USERNAME)

    kubectl_apply_yaml(content)
    log(f"  ArgoCD Application '{name}' applied.")
    applied.append(name)

# ---------------------------------------------------------------------------
# Wait for ArgoCD to sync
# ---------------------------------------------------------------------------
if not applied:
    die("No applications were applied.")

print()
print("============================================")
print("  Waiting for ArgoCD to sync...")
print("  (Ctrl+C to stop watching — ArgoCD continues syncing in background)")
print("============================================")

POLL_INTERVAL = 15
MAX_WAIT      = 60 * 10  # 10 minutes
elapsed       = 0
pending       = list(applied)
results       = {}

try:
    while pending and elapsed < MAX_WAIT:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        still_pending = []
        for name in pending:
            out, _ = run_cmd(
                ["kubectl", "get", "application", name,
                 "-n", "argocd",
                 "-o", "jsonpath={.status.sync.status}|{.status.health.status}"],
                capture=True, ok_fail=True,
            )
            parts  = out.split("|")
            sync   = parts[0] if parts else "Unknown"
            health = parts[1] if len(parts) > 1 else "Unknown"

            if sync == "Synced" and health == "Healthy":
                results[name] = "Synced/Healthy"
                log(f"{name}: Synced & Healthy")
            elif health == "Degraded":
                results[name] = "Degraded"
                warn(f"{name}: Degraded — check logs: kubectl logs -n {ENV} deployment/{name}")
            else:
                info(f"{name}: sync={sync}, health={health}  ({elapsed}s elapsed)")
                still_pending.append(name)

        pending = still_pending

except KeyboardInterrupt:
    print()
    warn("Stopped watching. ArgoCD is still syncing in the background.")
    print()
    print("  Check status:")
    print("    kubectl get applications -n argocd")
    sys.exit(0)

if pending:
    warn(f"Timed out after {MAX_WAIT}s. These apps are still syncing:")
    for name in pending:
        print(f"    {name}")
    print()
    print("  Check with:")
    print("    kubectl get applications -n argocd")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  Deployment Summary")
print("============================================")
print()
print(f"  Environment : {ENV}")
print()
for name in applied:
    outcome = results.get(name, "still syncing")
    color   = GREEN if outcome == "Synced/Healthy" else YELLOW
    print(f"  {color}{name:<30} {outcome}{NC}")

if skipped:
    print()
    for name in skipped:
        print(f"  {YELLOW}{name:<30} skipped (manifest missing){NC}")

print()
alb_hostname, _ = run_cmd(
    ["kubectl", "get", "ingress", "pharma-ui", "-n", ENV,
     "-o", "jsonpath={.status.loadBalancer.ingress[0].hostname}"],
    capture=True, ok_fail=True,
)
if alb_hostname:
    print(f"  Application URL : http://{alb_hostname}/")

print()
print("  ArgoCD UI : kubectl port-forward svc/argocd-server -n argocd 8080:443")
print()
print("Next step: python3 scripts/06_verify_deployment.py")
