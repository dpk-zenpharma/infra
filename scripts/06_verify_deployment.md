# Verify the deployment

This guide explains what `06_verify_deployment.py` checks, how to run it, and
what its result does—and does not—tell you.

## The big picture

Scripts 01–05 install the cluster components, configure GitOps and secrets,
build images, and ask Argo CD to deploy services. This final script checks the
selected environment and reports issues it finds.

```text
05 applies Argo CD Applications
             |
             v
Argo CD syncs the workloads and the ALB is provisioned
             |
             v
06 checks pods, Argo CD, secrets, Ingress, and selected HTTP paths
```

Run this after [script 05](./05_deploy_services.md). If Argo CD is still
syncing or the ALB is still being created, wait and run the verification again.

## What it checks, and why

| Check | Why it matters | What the script looks at |
|---|---|---|
| Pods | Confirms that Kubernetes workloads in the environment can become Ready. | Waits for pods to appear, then waits for all pods in the selected namespace to become Ready. |
| Argo CD Applications | Shows whether Argo CD applied the desired configuration and considers applications healthy. | Records a failure if an Application is not `Synced` or not `Healthy`. |
| External Secrets | Confirms that ESO reports the configured secret copies as ready. | Records a failure for an `ExternalSecret` whose Ready status is not `True`. |
| Services and Ingress | Shows the in-cluster services and whether an Ingress has an ALB hostname. | Prints services/Ingresses and looks for the hostname on `pharma-ui`, then falls back to another Ingress. |
| HTTP paths | Gives a basic reachability/status check through the ALB. | Requests selected UI and API health paths when a hostname is available. |

## Before you start

- Script 05 should have applied the selected applications.
- Python 3 and `kubectl` must be available (`kubectl` is checked using
  `which`; on Windows, use WSL).
- `kubectl` must target the cluster containing the deployment.
- For HTTP checks, the AWS Load Balancer Controller must have provisioned an
  ALB with a hostname that is reachable from the machine running this script.

This script is for checking/reporting; it does not change Kubernetes resources.
Its HTTP requests use plain HTTP and do not authenticate. They are basic
reachability checks, not full end-to-end tests.

## Values to provide

| Value | What to enter | Where to get it | Why this script needs it |
|---|---|---|---|
| `ENV` | `dev`, `qa`, or `prod` | Choose the environment where you deployed the applications. | Selects the Kubernetes namespace whose pods, secrets, services, and Ingress resources are checked. Default: `dev`. |
| `TIMEOUT_PODS` | Maximum number of seconds to wait for all namespace pods to become Ready | Use a number of seconds. Default: `300`. | Sets the readiness wait duration after pods appear. The script first waits up to 60 seconds for any pods to appear. |

Set either value as an environment variable to skip its prompt (the environment
is also read from `ENV`). `TIMEOUT_PODS` must be an integer.

## Run it

From the `infra` repository root:

```bash
python3 scripts/06_verify_deployment.py
```

Choose the environment. Review the printed checks and summary. The script exits
with code `0` when it records no failed checks, and a non-zero code when it
records one or more failures.

## Details and limits of the checks

- **Pods:** waits up to 60 seconds for pods to appear. If none appear, it warns
  but does not count that alone as a failed check. If pods exist, it waits up
  to `TIMEOUT_PODS` for them to become Ready.
- **Argo CD:** checks Applications in namespace `argocd`, and records a failure
  when an Application is not `Synced` or not `Healthy`.
- **External Secrets:** checks the `ExternalSecret` resources found in the
  selected environment namespace. A resource not Ready is a failure.
- **Ingress/ALB:** prints Services and Ingresses and looks for an ALB hostname.
  If no hostname is ready, it warns and skips HTTP checks.
- **HTTP:** when a hostname is available, sends plain-HTTP requests to `/`,
  `/api/actuator/health`, `/api/auth/actuator/health`,
  `/api/catalog/actuator/health`, `/api/inventory/actuator/health`,
  `/api/suppliers/actuator/health`, and
  `/api/manufacturing/actuator/health`. HTTP `200`, `301`, and `302` count as
  success. Other responses and request errors count as failures.

The HTTP checks do not cover every service (for example, QC and notification
have no dedicated check here). A passing result means these particular checks
passed, not that every feature or user flow has been tested. Also, the script
does not fail solely because no pods or no ALB hostname appeared; read its
warnings along with the final summary.

## If a check fails

The script prints suggested commands. You can also inspect the deployment with:

```bash
kubectl get applications -n argocd
kubectl get pods -n <env>
kubectl describe pod <pod-name> -n <env>
kubectl logs -n <env> deployment/<service-name> --previous
kubectl describe externalsecret db-credentials -n <env>
kubectl get ingress -n <env>
```

Replace `<env>`, `<pod-name>`, and `<service-name>` with the actual values.
Confirm the current Kubernetes context before investigating or making changes.
