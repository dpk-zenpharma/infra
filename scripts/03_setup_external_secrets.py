#!/usr/bin/env python3
# =============================================================================
# Stage 2 - Configure External Secrets Operator
#
# Creates a ClusterSecretStore and ExternalSecrets so pods can pull
# db-credentials and jwt-secret from AWS Secrets Manager automatically.
#
# Uses IRSA (IAM Roles for Service Accounts) - no static AWS keys stored
# anywhere. The IAM role is created by Terraform in Stage 1.
#
# Run from the root of the dpp-assignment3 directory.
# =============================================================================

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

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

def run_cmd(args, ok_fail=False, capture=False):
    if capture:
        result = subprocess.run(args, capture_output=True, text=True)
        return result.stdout.strip(), result.returncode
    result = subprocess.run(args)
    if result.returncode != 0 and not ok_fail:
        die(f"Command failed: {' '.join(str(a) for a in args)}")
    return None, result.returncode

def kubectl_apply_yaml(yaml_str):
    result = subprocess.run(["kubectl", "apply", "-f", "-"], input=yaml_str, text=True)
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
print("  Zen Pharma -- External Secrets Setup")
print("============================================")
print()
print("  This script wires up External Secrets Operator to AWS Secrets Manager")
print("  using IRSA (IAM Roles for Service Accounts).")
print()
print("  No static AWS keys are stored - pods authenticate via the IAM role")
print("  that Terraform created in Stage 1.")
print()
print("  You will be asked for 4 values:")
print("    1. Target environment  - dev, qa, or prod")
print("    2. AWS region          - where Secrets Manager is configured")
print("    3. AWS account ID      - 12-digit number from AWS console")
print("    4. ESO IAM role name   - created by Terraform (check Terraform outputs)")
print()

ENV            = prompt_choice("ENV", "Target environment (determines which Secrets Manager paths to sync)",
                               ["dev", "qa", "prod"])
AWS_REGION     = prompt("AWS_REGION", "AWS region where your Secrets Manager secrets are stored",
                        "us-east-1", "us-east-1")
AWS_ACCOUNT_ID = prompt("AWS_ACCOUNT_ID",
                        "AWS account ID (12-digit number - find it in the top-right of the AWS console, or run: aws sts get-caller-identity --query Account --output text)",
                        "<aws-account-id>", "873135413040")

default_role   = f"pharma-{ENV}-eso-role"
ESO_ROLE_NAME  = prompt("ESO_ROLE_NAME",
                        "ESO IAM role name (created by Terraform - check 'Terraform Apply' output or AWS IAM console)",
                        "pharma-dev-eso-role", default_role)

ESO_ROLE_ARN = f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/{ESO_ROLE_NAME}"

print()
print("  ----- Configuration Summary -----")
print(f"  Environment  : {ENV}")
print(f"  AWS Region   : {AWS_REGION}")
print(f"  Account ID   : {AWS_ACCOUNT_ID}")
print(f"  ESO Role ARN : {ESO_ROLE_ARN}")
print("  ---------------------------------")
print()
print("  Secrets will be synced from these Secrets Manager paths:")
print(f"    /pharma/{ENV}/db-credentials  ->  Kubernetes Secret 'db-credentials'")
print(f"    /pharma/{ENV}/jwt-secret       ->  Kubernetes Secret 'jwt-secret'")
print()
confirm = input("  Continue? [Y/n]: ").strip() or "Y"
if confirm.upper() != "Y":
    print("Aborted.")
    sys.exit(0)
print()

# ---------------------------------------------------------------------------
# Ensure target namespace exists
# ---------------------------------------------------------------------------
dry_run, _ = run_cmd(
    ["kubectl", "create", "namespace", ENV, "--dry-run=client", "-o", "yaml"],
    capture=True,
)
kubectl_apply_yaml(dry_run)
log(f"Namespace '{ENV}' ready.")

# ---------------------------------------------------------------------------
# Step 1 - Annotate ESO service account with IRSA role ARN
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 1 of 4: IRSA annotation on ESO service account")
print("--------------------------------------------")
print()
print("  What is IRSA?")
print("  IRSA (IAM Roles for Service Accounts) lets a Kubernetes service account")
print("  assume an AWS IAM role. Pods running as that service account automatically")
print("  get short-lived AWS credentials injected via a projected volume token.")
print("  No passwords or access keys are stored anywhere.")
print()

run_cmd([
    "kubectl", "annotate", "serviceaccount", "external-secrets",
    "--namespace", "external-secrets",
    f"eks.amazonaws.com/role-arn={ESO_ROLE_ARN}",
    "--overwrite",
])
log("ESO service account annotated with IAM role.")

run_cmd(["kubectl", "rollout", "restart", "deployment/external-secrets", "-n", "external-secrets"])
run_cmd(["kubectl", "rollout", "status",  "deployment/external-secrets", "-n", "external-secrets",
         "--timeout=120s"])
log("ESO pods restarted.")

# ---------------------------------------------------------------------------
# Step 2 - ClusterSecretStore
# ---------------------------------------------------------------------------
info("Waiting for ESO CRDs to be fully established...")
run_cmd([
    "kubectl", "wait", "--for=condition=established",
    "crd/clustersecretstores.external-secrets.io",
    "crd/externalsecrets.external-secrets.io",
    "--timeout=60s",
])

# Clear kubectl discovery cache so newly registered CRD types are visible
discovery_cache = os.path.expanduser("~/.kube/cache/discovery")
if os.path.isdir(discovery_cache):
    shutil.rmtree(discovery_cache)

print()
print("--------------------------------------------")
print("  Step 2 of 4: ClusterSecretStore (IRSA auth)")
print("--------------------------------------------")

cluster_secret_store = f"""\
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: aws-secrets-manager
spec:
  provider:
    aws:
      service: SecretsManager
      region: {AWS_REGION}
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
"""
kubectl_apply_yaml(cluster_secret_store)
log("ClusterSecretStore 'aws-secrets-manager' created.")

# ---------------------------------------------------------------------------
# Step 3 - ExternalSecrets for db-credentials and jwt-secret
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print(f"  Step 3 of 4: ExternalSecrets -> namespace '{ENV}'")
print("--------------------------------------------")

db_external_secret = f"""\
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-credentials
  namespace: {ENV}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: db-credentials
    creationPolicy: Owner
  data:
    - secretKey: DB_USERNAME
      remoteRef:
        key: /pharma/{ENV}/db-credentials
        property: username
    - secretKey: DB_PASSWORD
      remoteRef:
        key: /pharma/{ENV}/db-credentials
        property: password
    - secretKey: SPRING_DATASOURCE_USERNAME
      remoteRef:
        key: /pharma/{ENV}/db-credentials
        property: username
    - secretKey: SPRING_DATASOURCE_PASSWORD
      remoteRef:
        key: /pharma/{ENV}/db-credentials
        property: password
    - secretKey: DB_HOST
      remoteRef:
        key: /pharma/{ENV}/db-credentials
        property: host
"""
kubectl_apply_yaml(db_external_secret)

jwt_external_secret = f"""\
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: jwt-secret
  namespace: {ENV}
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets-manager
    kind: ClusterSecretStore
  target:
    name: jwt-secret
    creationPolicy: Owner
  data:
    - secretKey: JWT_SECRET
      remoteRef:
        key: /pharma/{ENV}/jwt-secret
        property: secret
"""
kubectl_apply_yaml(jwt_external_secret)
log(f"ExternalSecrets created in namespace '{ENV}'.")

# ---------------------------------------------------------------------------
# Step 4 - Wait for secrets to sync
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 4 of 4: Waiting for secrets to sync...")
print("--------------------------------------------")

info("Polling for up to 90 seconds...")
TIMEOUT = 90
elapsed = 0
all_synced = False

while elapsed < TIMEOUT:
    db_status, _ = run_cmd(
        ["kubectl", "get", "externalsecret", "db-credentials", "-n", ENV,
         "-o", "jsonpath={.status.conditions[?(@.type==\"Ready\")].reason}"],
        capture=True, ok_fail=True,
    )
    jwt_status, _ = run_cmd(
        ["kubectl", "get", "externalsecret", "jwt-secret", "-n", ENV,
         "-o", "jsonpath={.status.conditions[?(@.type==\"Ready\")].reason}"],
        capture=True, ok_fail=True,
    )
    db_status  = db_status  or "NotFound"
    jwt_status = jwt_status or "NotFound"

    if db_status == "SecretSynced" and jwt_status == "SecretSynced":
        all_synced = True
        break

    print(f"  db-credentials: {db_status} | jwt-secret: {jwt_status} -- waiting...")
    time.sleep(10)
    elapsed += 10

print()
run_cmd(["kubectl", "get", "externalsecret", "-n", ENV])
print()

if all_synced:
    log(f"Both secrets synced successfully into namespace '{ENV}'.")
else:
    warn("Secrets not yet synced. Common causes:")
    warn("")
    warn(f"  1. Secrets Manager paths do not exist - create them first:")
    warn(f"       /pharma/{ENV}/db-credentials  (JSON: {{\"username\":\"...\",\"password\":\"...\"}})")
    warn(f"       /pharma/{ENV}/jwt-secret       (JSON: {{\"secret\":\"...\"}})")
    warn("")
    warn(f"  2. IAM role '{ESO_ROLE_NAME}' is missing secretsmanager:GetSecretValue")
    warn("")
    warn("  3. OIDC provider not configured on the EKS cluster")
    warn("")
    warn("  Debug command:")
    warn(f"    kubectl describe externalsecret db-credentials -n {ENV}")

print()
log("External Secrets setup complete.")
print()
print("Next step: ./scripts/04_run_pipeline.py")
