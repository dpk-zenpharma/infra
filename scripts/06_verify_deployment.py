#!/usr/bin/env python3
# =============================================================================
# Stage 4 - Verify Deployment
#
# Runs health checks to confirm everything is working:
#   1. Kubernetes pods  - all Running and Ready
#   2. ArgoCD apps      - all Synced and Healthy
#   3. External Secrets - all SecretSynced
#   4. Services/Ingress - resources created
#   5. HTTP endpoints   - health checks via ALB
#
# Run from the root of the dpp-assignment3 directory.
# =============================================================================

import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
RED    = "\033[0;31m"
GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
CYAN   = "\033[0;36m"
BLUE   = "\033[0;34m"
NC     = "\033[0m"

def _ts():
    return datetime.now().strftime("%H:%M:%S")

def log(msg):   print(f"{GREEN}[{_ts()}] OK  {msg}{NC}")
def warn(msg):  print(f"{YELLOW}[{_ts()}] !!  {msg}{NC}")
def info(msg):  print(f"{BLUE}[{_ts()}]    {msg}{NC}")
def die(msg):
    print(f"{RED}[{_ts()}] ERR {msg}{NC}", file=sys.stderr)
    sys.exit(1)

ERRORS = 0

def fail(msg):
    global ERRORS
    print(f"{RED}[{_ts()}] FAIL {msg}{NC}", file=sys.stderr)
    ERRORS += 1

def run_cmd(args, ok_fail=False, capture=False):
    if capture:
        result = subprocess.run(args, capture_output=True, text=True)
        return result.stdout.strip(), result.returncode
    result = subprocess.run(args)
    if result.returncode != 0 and not ok_fail:
        die(f"Command failed: {' '.join(str(a) for a in args)}")
    return None, result.returncode

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
print("  Zen Pharma -- Deployment Verification")
print("============================================")
print()
print("  This script checks that all services are healthy in a given environment.")
print()

ENV = os.environ.get("ENV", "")

if not ENV:
    print(f"{CYAN}  Target environment (which namespace to check){NC}")
    print("    1) dev   - development environment")
    print("    2) qa    - quality assurance environment")
    print("    3) prod  - production environment")
    raw = input("    Enter number [1]: ").strip() or "1"
    ENV = {"1": "dev", "2": "qa", "3": "prod"}.get(raw)
    if not ENV:
        die(f"Invalid choice '{raw}'.")

if ENV not in ("dev", "qa", "prod"):
    die("ENV must be dev, qa, or prod.")

TIMEOUT_PODS = int(os.environ.get("TIMEOUT_PODS", "300"))
ARGOCD_NS    = "argocd"

print()
print(f"  Environment : {ENV}")
print()

# ---------------------------------------------------------------------------
# Check 1 - Kubernetes Pods
# ---------------------------------------------------------------------------
print("--------------------------------------------")
print(f"  Check 1 of 5: Kubernetes Pods (namespace: {ENV})")
print("--------------------------------------------")

info(f"Waiting up to 60s for pods to appear in namespace '{ENV}'...")
elapsed = 0
pod_count = 0

while elapsed < 60:
    pods_out, _ = run_cmd(
        ["kubectl", "get", "pods", "-n", ENV, "--no-headers"],
        capture=True, ok_fail=True,
    )
    pod_count = len([l for l in pods_out.splitlines() if l.strip()])
    if pod_count > 0:
        break
    print(f"  No pods yet in '{ENV}' ({elapsed}s elapsed) -- ArgoCD may still be syncing...")
    time.sleep(10)
    elapsed += 10

if elapsed >= 60:
    warn(f"No pods found in '{ENV}' after 60s.")
    warn("  ArgoCD may not have synced yet. Check: kubectl get applications -n argocd")
else:
    info(f"Waiting up to {TIMEOUT_PODS}s for all pods to become Ready...")
    _, rc = run_cmd(
        ["kubectl", "wait", "pod", "--all", "-n", ENV,
         "--for=condition=Ready", f"--timeout={TIMEOUT_PODS}s"],
        ok_fail=True,
    )
    if rc == 0:
        log("All pods are Running and Ready.")
    else:
        fail("One or more pods are not Ready. See pod list below.")

print()
run_cmd(["kubectl", "get", "pods", "-n", ENV, "-o", "wide"])
print()

# ---------------------------------------------------------------------------
# Check 2 - ArgoCD Application health
# ---------------------------------------------------------------------------
print("--------------------------------------------")
print("  Check 2 of 5: ArgoCD Application Status")
print("--------------------------------------------")
print()

run_cmd(["kubectl", "get", "applications", "-n", ARGOCD_NS, "-o", "wide"], ok_fail=True)
print()

apps_out, _ = run_cmd(
    ["kubectl", "get", "applications", "-n", ARGOCD_NS, "--no-headers"],
    capture=True, ok_fail=True,
)
for line in apps_out.splitlines():
    parts = line.split()
    if len(parts) >= 4:
        app_name    = parts[0]
        sync_status = parts[2]
        health      = parts[3]
        if sync_status != "Synced" or health != "Healthy":
            fail(f"App '{app_name}': sync={sync_status}, health={health}")

if ERRORS == 0:
    log("All ArgoCD applications are Synced and Healthy.")

# ---------------------------------------------------------------------------
# Check 3 - External Secrets
# ---------------------------------------------------------------------------
print("--------------------------------------------")
print("  Check 3 of 5: External Secrets")
print("--------------------------------------------")
print()

run_cmd(["kubectl", "get", "externalsecret", "-n", ENV], ok_fail=True)
print()

es_out, _ = run_cmd(
    ["kubectl", "get", "externalsecret", "-n", ENV, "--no-headers"],
    capture=True, ok_fail=True,
)
for line in es_out.splitlines():
    parts = line.split()
    if len(parts) >= 5:
        es_name  = parts[0]
        es_ready = parts[4]
        if es_ready != "True":
            fail(f"ExternalSecret '{es_name}' is not Ready (Ready={es_ready})")

if ERRORS == 0:
    log("All ExternalSecrets are synced.")

# ---------------------------------------------------------------------------
# Check 4 - Services and Ingress
# ---------------------------------------------------------------------------
print("--------------------------------------------")
print("  Check 4 of 5: Services and Ingress")
print("--------------------------------------------")
print()

run_cmd(["kubectl", "get", "svc", "-n", ENV])
print()
run_cmd(["kubectl", "get", "ingress", "-n", ENV], ok_fail=True)
print()

# ALB hostname is provisioned per-Ingress by the AWS Load Balancer Controller.
# We read it from the pharma-ui ingress (the group's primary entry point).
alb_hostname, _ = run_cmd(
    ["kubectl", "get", "ingress", "pharma-ui", "-n", ENV,
     "-o", "jsonpath={.status.loadBalancer.ingress[0].hostname}"],
    capture=True, ok_fail=True,
)

if not alb_hostname:
    # Fallback: try any ingress in the namespace
    alb_hostname, _ = run_cmd(
        ["kubectl", "get", "ingress", "-n", ENV,
         "-o", "jsonpath={.items[0].status.loadBalancer.ingress[0].hostname}"],
        capture=True, ok_fail=True,
    )

if alb_hostname:
    log(f"ALB hostname: {alb_hostname}")
else:
    warn("ALB hostname not available yet -- the AWS Load Balancer Controller may still be provisioning.")
    warn("  Check: kubectl get ingress -n " + ENV)

# ---------------------------------------------------------------------------
# Check 5 - HTTP health endpoints
# ---------------------------------------------------------------------------
if alb_hostname:
    print("--------------------------------------------")
    print("  Check 5 of 5: HTTP Endpoint Health")
    print("--------------------------------------------")
    print()

    health_paths = {
        "pharma-ui":             "/",
        "api-gateway":           "/api/actuator/health",
        "auth-service":          "/api/auth/actuator/health",
        "drug-catalog-service":  "/api/catalog/actuator/health",
        "inventory-service":     "/api/inventory/actuator/health",
        "supplier-service":      "/api/suppliers/actuator/health",
        "manufacturing-service": "/api/manufacturing/actuator/health",
    }

    base_url = f"http://{alb_hostname}"

    for service, path in health_paths.items():
        url = f"{base_url}{path}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                http_code = resp.status
        except urllib.error.HTTPError as e:
            http_code = e.code
        except Exception:
            http_code = 0

        if http_code in (200, 301, 302):
            log(f"{service}: HTTP {http_code}  <--  {url}")
        else:
            fail(f"{service}: HTTP {http_code}  <--  {url}  (expected 200/301/302)")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
print("============================================")
if ERRORS == 0:
    print(f"{GREEN}  ALL CHECKS PASSED{NC}")
    print()
    if alb_hostname:
        print(f"  Application URL : http://{alb_hostname}/")
    print("  ArgoCD UI       : https://localhost:8080")
    print("                    (kubectl port-forward svc/argocd-server -n argocd 8080:443)")
else:
    print(f"{RED}  {ERRORS} CHECK(S) FAILED{NC}")
    print()
    print("  Troubleshooting commands:")
    print(f"    kubectl describe pod <pod-name> -n {ENV}")
    print(f"    kubectl logs -n {ENV} deployment/<service-name> --previous")
    print(f"    kubectl describe externalsecret db-credentials -n {ENV}")
    print("    kubectl get applications -n argocd")
print("============================================")
print()

sys.exit(ERRORS)
