#!/usr/bin/env python3
# =============================================================================
# Stage 2 - Install Kubernetes Pre-requisites
#
# Installs on the EKS cluster (must already exist from Stage 1 Terraform):
#   1. AWS Load Balancer Controller - exposes services via AWS ALB
#   2. ArgoCD                       - GitOps CD controller
#   3. External Secrets Operator    - syncs AWS Secrets Manager -> K8s Secrets
#
# Run from anywhere — paths are resolved relative to this script's location.
# =============================================================================

import os
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

# ---------------------------------------------------------------------------
# run_cmd: run a shell command, streaming output; die on failure unless ok_fail=True
# ---------------------------------------------------------------------------
def run_cmd(args, ok_fail=False, capture=False):
    if capture:
        result = subprocess.run(args, capture_output=True, text=True)
        return result.stdout.strip(), result.returncode
    result = subprocess.run(args)
    if result.returncode != 0 and not ok_fail:
        die(f"Command failed: {' '.join(str(a) for a in args)}")
    return None, result.returncode

# ---------------------------------------------------------------------------
# prompt: ask the user for a value, skip if already in environment
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

# ---------------------------------------------------------------------------
# Verify required tools are installed
# ---------------------------------------------------------------------------
print()
print("Checking required tools...")
for tool in ["kubectl", "helm", "aws"]:
    rc = subprocess.run(["which", tool], capture_output=True).returncode
    if rc != 0:
        die(f"{tool} not found. Install it before running this script.")
log("kubectl, helm, and aws CLI found.")

# ---------------------------------------------------------------------------
# Collect inputs
# ---------------------------------------------------------------------------
print()
print("============================================")
print("  Zen Pharma -- Pre-requisites Installer")
print("============================================")
print()
print("  This script installs AWS Load Balancer Controller, ArgoCD, and")
print("  External Secrets Operator on your EKS cluster using Helm.")
print()
print("  You will be asked for 4 values:")
print("    1. EKS cluster name         - from Terraform outputs or AWS console")
print("    2. AWS region               - where your cluster is running")
print("    3. VPC ID                   - VPC where the cluster lives (auto-fetched if blank)")
print("    4. ALB controller role ARN  - IAM role ARN for the ALB controller")
print("       (arn:aws:iam::<account-id>:role/<project>-<env>-alb-controller-role)")
print()

CLUSTER_NAME        = prompt("CLUSTER_NAME",        "EKS cluster name",
                             "pharma-dev-cluster", "pharma-dev-cluster")
AWS_REGION          = prompt("AWS_REGION",          "AWS region where the cluster is deployed",
                             "us-east-1", "us-east-1")
ALB_CONTROLLER_ROLE = prompt("ALB_CONTROLLER_ROLE", "IAM role ARN for the AWS Load Balancer Controller",
                             "arn:aws:iam::<aws-account-id>:role/pharma-dev-alb-controller-role",
                             "arn:aws:iam::873135413040:role/pharma-dev-alb-controller-role")

default_gitops = os.path.join(DEFAULT_PROJECT_ROOT, "gitops")
GITOPS_PATH         = prompt("GITOPS_PATH",         "Local path to your gitops repo",
                             default_gitops, default_gitops)

# Auto-fetch VPC ID from EKS cluster if not set in environment
VPC_ID = os.environ.get("VPC_ID", "")
if not VPC_ID:
    info(f"Auto-fetching VPC ID for cluster '{CLUSTER_NAME}'...")
    VPC_ID, rc = run_cmd(
        ["aws", "eks", "describe-cluster", "--name", CLUSTER_NAME,
         "--region", AWS_REGION,
         "--query", "cluster.resourcesVpcConfig.vpcId",
         "--output", "text"],
        capture=True, ok_fail=True,
    )
    if rc == 0 and VPC_ID and VPC_ID != "None":
        log(f"VPC ID auto-detected: {VPC_ID}")
    else:
        VPC_ID = prompt("VPC_ID", "VPC ID where the EKS cluster runs",
                        "vpc-xxxxxxxxxxxxxxxxx")

print()
print("  ----- Configuration Summary -----")
print(f"  Cluster          : {CLUSTER_NAME}")
print(f"  Region           : {AWS_REGION}")
print(f"  VPC ID           : {VPC_ID}")
print(f"  ALB role ARN     : {ALB_CONTROLLER_ROLE}")
print("  ---------------------------------")
print()
confirm = input("  Proceed with installation? [Y/n]: ").strip() or "Y"
if confirm.upper() != "Y":
    print("Aborted.")
    sys.exit(0)
print()

# ---------------------------------------------------------------------------
# Configure kubectl
# ---------------------------------------------------------------------------
info(f"Updating kubeconfig for cluster '{CLUSTER_NAME}' in '{AWS_REGION}'...")
_, rc = run_cmd(
    ["aws", "eks", "update-kubeconfig", "--region", AWS_REGION, "--name", CLUSTER_NAME],
    ok_fail=True,
)
if rc != 0:
    warn("kubeconfig update failed - continuing with existing context")

ctx, _ = run_cmd(["kubectl", "config", "current-context"], capture=True)
log(f"kubectl context: {ctx}")

# ---------------------------------------------------------------------------
# Add Helm repositories
# ---------------------------------------------------------------------------
print()
info("Adding Helm repositories...")
for name, url in [
    ("eks",              "https://aws.github.io/eks-charts"),
    ("external-secrets", "https://charts.external-secrets.io"),
    ("argo",             "https://argoproj.github.io/argo-helm"),
]:
    run_cmd(["helm", "repo", "add", name, url, "--force-update"], ok_fail=True)
run_cmd(["helm", "repo", "update"])
log("Helm repos updated.")

# ---------------------------------------------------------------------------
# Step 1 - AWS Load Balancer Controller
#
# Watches Ingress resources with ingressClassName: alb and provisions an
# AWS Application Load Balancer for each IngressGroup. Runs in kube-system
# and uses IRSA (IAM Roles for Service Accounts) to call AWS APIs.
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 1 of 3: AWS Load Balancer Controller")
print("--------------------------------------------")

ALB_VALUES_FILE = os.path.join(GITOPS_PATH, "k8s/ingress/alb-controller-values.yaml")

alb_cmd = [
    "helm", "upgrade", "--install", "aws-load-balancer-controller",
    "eks/aws-load-balancer-controller",
    "--namespace", "kube-system",
    "--set", f"clusterName={CLUSTER_NAME}",
    "--set", f"region={AWS_REGION}",
    "--set", f"vpcId={VPC_ID}",
    "--set", "serviceAccount.create=true",
    "--set", "serviceAccount.name=aws-load-balancer-controller",
    "--set", f"serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn={ALB_CONTROLLER_ROLE}",
    "--wait", "--timeout", "5m",
]

if os.path.isfile(ALB_VALUES_FILE):
    alb_cmd += ["-f", ALB_VALUES_FILE]
    info(f"Using values file: {ALB_VALUES_FILE}")

run_cmd(alb_cmd)
log("AWS Load Balancer Controller installed.")

alb_version, _ = run_cmd(
    ["helm", "list", "-n", "kube-system", "--filter", "aws-load-balancer-controller",
     "--short"],
    capture=True, ok_fail=True,
)
log(f"Release: {alb_version or 'aws-load-balancer-controller'}")
print("  NOTE: ALB hostnames are provisioned per-Ingress after ArgoCD syncs apps.")

# The ALB controller's webhook TLS cert is generated by a Helm certgen job.
# If a previous install left a stale cert, subsequent webhook calls (e.g. from
# ArgoCD's Service creation) will fail with x509 errors. Deleting and letting
# Helm recreate them ensures the cert matches the running controller.
info("Refreshing ALB webhook certificates...")
for wh_type in ["mutatingwebhookconfiguration", "validatingwebhookconfiguration"]:
    run_cmd(["kubectl", "delete", wh_type, "aws-load-balancer-webhook"],
            ok_fail=True)

run_cmd([
    "helm", "upgrade", "aws-load-balancer-controller",
    "eks/aws-load-balancer-controller",
    "--namespace", "kube-system",
    "--set", f"clusterName={CLUSTER_NAME}",
    "--set", f"region={AWS_REGION}",
    "--set", f"vpcId={VPC_ID}",
    "--set", "serviceAccount.create=true",
    "--set", "serviceAccount.name=aws-load-balancer-controller",
    "--set", f"serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn={ALB_CONTROLLER_ROLE}",
    "--wait", "--timeout", "3m",
])
log("ALB webhook certificates refreshed.")

# ---------------------------------------------------------------------------
# Step 2 - ArgoCD
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 2 of 3: ArgoCD")
print("--------------------------------------------")

run_cmd([
    "helm", "upgrade", "--install", "argocd", "argo/argo-cd",
    "--namespace", "argocd",
    "--create-namespace",
    "--wait", "--timeout", "10m",
])

import base64
argocd_password_b64, _ = run_cmd(
    ["kubectl", "-n", "argocd", "get", "secret", "argocd-initial-admin-secret",
     "-o", "jsonpath={.data.password}"],
    capture=True,
)
argocd_password = base64.b64decode(argocd_password_b64).decode().strip()

log("ArgoCD installed.")
print()
print("  ============================================================")
print("  IMPORTANT: Save the ArgoCD credentials below")
print("  ============================================================")
print("  Username : admin")
print(f"  Password : {argocd_password}")
print()
print("  To access the ArgoCD UI:")
print("    kubectl port-forward svc/argocd-server -n argocd 8080:443")
print("    Then open: https://localhost:8080")
print("  ============================================================")
print()

ingress_file = os.path.join(GITOPS_PATH, "argocd/install/argocd-ingress.yaml")
if os.path.isfile(ingress_file):
    run_cmd(["kubectl", "apply", "-f", ingress_file])
    log("ArgoCD ingress applied.")

# ---------------------------------------------------------------------------
# Step 3 - External Secrets Operator
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Step 3 of 3: External Secrets Operator")
print("--------------------------------------------")

run_cmd([
    "helm", "upgrade", "--install", "external-secrets", "external-secrets/external-secrets",
    "--namespace", "external-secrets",
    "--create-namespace",
    "--set", "installCRDs=true",
    "--wait", "--timeout", "5m",
])

log("External Secrets Operator installed.")

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
print()
print("--------------------------------------------")
print("  Verification")
print("--------------------------------------------")
print()
print("AWS Load Balancer Controller pods (namespace: kube-system):")
run_cmd(["kubectl", "get", "pods", "-n", "kube-system",
         "-l", "app.kubernetes.io/name=aws-load-balancer-controller"])
print()
print("ArgoCD pods (namespace: argocd):")
run_cmd(["kubectl", "get", "pods", "-n", "argocd"])
print()
print("External Secrets pods (namespace: external-secrets):")
run_cmd(["kubectl", "get", "pods", "-n", "external-secrets"])

print()
log("All pre-requisites installed successfully.")
print()
print("  Summary:")
print(f"    ALB controller   : installed in kube-system")
print(f"    ArgoCD pass      : {argocd_password}")
print()
print("  ALB hostnames will appear in 'kubectl get ingress -n <env>'")
print("  once ArgoCD has synced your applications.")
print()
print("Next step: ./scripts/02_bootstrap_argocd.py")
