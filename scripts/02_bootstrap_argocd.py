#!/usr/bin/env python3
# =============================================================================
# Stage 2 - Bootstrap ArgoCD
#
# After ArgoCD is installed (script 01), this script:
#   1. Registers your gitops repo in ArgoCD
#   2. Creates the pharma AppProject
#
# Application deployment is handled by 05_deploy_services.py
#
# Run from anywhere — paths are resolved relative to this script's location.
# =============================================================================

import getpass
import os
import re
import subprocess
import sys
from datetime import datetime

# Default project root is two levels above this script (infra/scripts/ → project root)
DEFAULT_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
NC     = "\033[0m"

def _ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):   print(f"{GREEN}[{_ts()}] OK  {msg}{NC}")
def warn(msg):  print(f"{YELLOW}[{_ts()}] !!  {msg}{NC}")
def info(msg):  print(f"{CYAN}[{_ts()}]    {msg}{NC}")
def die(msg):
    print(f"{RED}[{_ts()}] ERR {msg}{NC}", file=sys.stderr)
    sys.exit(1)

def run_cmd(args, ok_fail=False, capture=False, stdin_data=None):
    if capture:
        result = subprocess.run(args, capture_output=True, text=True)
        return result.stdout.strip(), result.returncode
    result = subprocess.run(args, input=stdin_data, text=bool(stdin_data))
    if result.returncode != 0 and not ok_fail:
        die(f"Command failed: {' '.join(str(a) for a in args)}")
    return None, result.returncode

def kubectl_apply_yaml(yaml_str):
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=yaml_str, text=True,
    )
    if result.returncode != 0:
        die("kubectl apply failed.")

# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------
def prompt(var_name, label, example, default=""):
    current = os.environ.get(var_name, "")
    if current:
        info(f"Using {var_name}={current}  (pre-set in environment, skipping prompt)")
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
        die(f"'{label}' is required and cannot be empty.")
    log(f"  {var_name} = {value}")
    return value

def prompt_secret(var_name, label, example):
    current = os.environ.get(var_name, "")
    if current:
        info(f"Using {var_name}=****** (pre-set in environment, skipping prompt)")
        return current

    print()
    print(f"{CYAN}  {label}{NC}")
    print(f"    Example : {example}")
    value = getpass.getpass("    Your value (input is hidden): ")
    if not value:
        die(f"'{label}' is required and cannot be empty.")
    log(f"  {var_name} = ****** (set)")
    return value

def prompt_choice(var_name, label, choices):
    current = os.environ.get(var_name, "")
    if current:
        info(f"Using {var_name}={current}  (pre-set in environment, skipping prompt)")
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

# ---------------------------------------------------------------------------
# Verify tools
# ---------------------------------------------------------------------------
if subprocess.run(["which", "kubectl"], capture_output=True).returncode != 0:
    die("kubectl not found.")

# ---------------------------------------------------------------------------
# Collect inputs
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  Zen Pharma -- ArgoCD Bootstrap")
print("============================================")
print()
print("  This script registers your gitops repo in ArgoCD,")
print("  creates the pharma AppProject, and deploys Applications.")
print()
print("  You will be asked for 4 values:")
print("    1. Target environment  - which K8s namespace to deploy to")
print("    2. GitOps repo URL     - HTTPS URL of your gitops fork")
print("    3. GitHub username     - your GitHub account name")
print("    4. GitHub token        - PAT with read access to gitops (input hidden)")
print()

ENV             = prompt_choice("ENV", "Target environment (choose the namespace to deploy applications to)",
                                ["dev", "qa", "prod"])
GITOPS_REPO_URL = prompt("GITOPS_REPO_URL", "GitOps repository HTTPS URL",
                          "https://github.com/<your-org>/gitops.git",
                          "https://github.com/zenpharma/gitops.git")

print(f"\n{CYAN}  NOTE: Enter your personal GitHub username, not the organization name.")
print(f"        GitHub authenticates users, not organizations. Your PAT grants")
print(f"        access to the org's repos because you are a member.{NC}\n")

GITHUB_USERNAME = prompt("GITHUB_USERNAME", "Your personal GitHub username",
                          "<your-github-username>", "ravdsun")
GITOPS_TOKEN    = prompt_secret("GITOPS_TOKEN",
                                "GitHub Personal Access Token with read access to gitops",
                                "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

default_gitops = os.path.join(DEFAULT_PROJECT_ROOT, "gitops")
GITOPS_PATH     = prompt("GITOPS_PATH", "Local path to your gitops repo",
                          default_gitops, default_gitops)

print()
print("  ----- Configuration Summary -----")
print(f"  Environment   : {ENV}")
print(f"  GitOps repo   : {GITOPS_REPO_URL}")
print(f"  GitHub user   : {GITHUB_USERNAME}")
print("  GitHub token  : ******")
print("  ---------------------------------")
print()
confirm = input("  Continue? [Y/n]: ").strip() or "Y"
if confirm.upper() != "Y":
    print("Aborted.")
    sys.exit(0)
print()

ARGOCD_NAMESPACE = "argocd"

# ---------------------------------------------------------------------------
# Verify ArgoCD is running
# ---------------------------------------------------------------------------
_, rc = run_cmd(
    ["kubectl", "get", "deployment", "argocd-server", "-n", ARGOCD_NAMESPACE],
    ok_fail=True, capture=True,
)
if rc != 0:
    die(f"ArgoCD not found in namespace '{ARGOCD_NAMESPACE}'. Run 01_install_prerequisites.py first.")

# ---------------------------------------------------------------------------
# Step 1 - Register gitops repo in ArgoCD
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 1 of 3: Register GitOps repository")
print("--------------------------------------------")

# dry-run=client generates the secret YAML, then pipe to apply (upsert)
dry_run_result = subprocess.run(
    [
        "kubectl", "create", "secret", "generic", "gitops-repo",
        "--namespace", ARGOCD_NAMESPACE,
        "--from-literal=type=git",
        f"--from-literal=url={GITOPS_REPO_URL}",
        f"--from-literal=username={GITHUB_USERNAME}",
        f"--from-literal=password={GITOPS_TOKEN}",
        "--dry-run=client", "-o", "yaml",
    ],
    capture_output=True, text=True,
)
if dry_run_result.returncode != 0:
    die("Failed to generate secret YAML.")

apply_result = subprocess.run(
    ["kubectl", "apply", "-f", "-"],
    input=dry_run_result.stdout, text=True,
)
if apply_result.returncode != 0:
    die("kubectl apply of gitops-repo secret failed.")

run_cmd([
    "kubectl", "label", "secret", "gitops-repo",
    "argocd.argoproj.io/secret-type=repository",
    "--namespace", ARGOCD_NAMESPACE,
    "--overwrite",
])

log(f"GitOps repo '{GITOPS_REPO_URL}' registered in ArgoCD.")

# ---------------------------------------------------------------------------
# Step 2 - Create the pharma AppProject
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 2 of 3: Create pharma AppProject")
print("--------------------------------------------")

project_file = os.path.join(GITOPS_PATH, "argocd/projects/pharma-project.yaml")
if os.path.isfile(project_file):
    with open(project_file) as f:
        content = f.read().replace("your-github-username", GITHUB_USERNAME)
    kubectl_apply_yaml(content)
    log(f"AppProject applied from {project_file}")
else:
    warn(f"{project_file} not found - creating AppProject inline.")
    inline_project = f"""\
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: pharma
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: Zen Pharma Platform
  sourceRepos:
    - "{GITOPS_REPO_URL}"
  destinations:
    - namespace: dev
      server: https://kubernetes.default.svc
    - namespace: qa
      server: https://kubernetes.default.svc
    - namespace: prod
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: ''
      kind: Namespace
  namespaceResourceWhitelist:
    - group: '*'
      kind: '*'
"""
    kubectl_apply_yaml(inline_project)
    log("AppProject created.")

print()
log(f"ArgoCD bootstrap complete for environment: {ENV}")
print()
print("  ArgoCD repo and AppProject are configured.")
print("  Applications will be deployed in step 05 after images are built.")
print()
print("  To open ArgoCD UI:")
print("    kubectl port-forward svc/argocd-server -n argocd 8080:443")
print("    Open: https://localhost:8080  (login: admin / <password from script 01>)")
print()
print("Next steps:")
print("  3. python3 scripts/03_setup_external_secrets.py")
print("  4. python3 scripts/04_run_pipeline.py    ← build images")
print("  5. python3 scripts/05_deploy_services.py ← deploy to cluster")
