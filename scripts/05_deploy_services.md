# Deploy selected services with Argo CD

This guide explains how `05_deploy_services.py` asks Argo CD to deploy services
to EKS, what must be ready first, and how to check the outcome.

## The big picture

The previous steps prepare the cluster and the application images. This script
applies Argo CD Application definitions from your local GitOps checkout.
Argo CD reads the referenced configuration and creates or updates the
Kubernetes resources for each selected service.

```text
02 connects Argo CD to GitOps
03 makes application secrets available
04 builds images and updates GitOps image tags
                    |
                    v
05 applies selected Argo CD Applications
                    |
                    v
Argo CD syncs workloads into the chosen namespace
                    |
                    v
06 checks deployment health and endpoints
```

Applying an Application asks Argo CD to deploy it; it does not mean the service
is already running or healthy. Argo CD syncs in the background.

## Before you start

Complete all three prerequisites for the selected environment:

1. **Script 02:** Argo CD has the GitOps repository credentials and `pharma`
   AppProject.
2. **Script 03:** ESO has synchronized the required secrets into the
   environment namespace.
3. **Script 04:** The selected services' images have been built/pushed and
   their image tags updated in GitOps.

Also make sure:

- Python 3 and `kubectl` are available (`kubectl` is checked using `which`; on
  Windows, use WSL).
- `kubectl` is connected to the intended EKS cluster.
- Your local GitOps checkout contains `argocd/apps/<env>/` and the Application
  manifests you want to apply.

The script checks that the environment directory exists, but it does not
validate that the secrets, image tags, or earlier setup stages are ready.

## Values to provide

| Value | What to enter | Where to get it | Why this script needs it |
|---|---|---|---|
| `ENV` | `dev`, `qa`, or `prod` | Choose the environment you prepared in scripts 02 and 03. | Chooses which `argocd/apps/<env>/` folder contains the Application manifests and which cluster namespace to deploy to. |
| `GITHUB_USERNAME` | Your personal GitHub username | Use the account name used in the GitOps repository URL. | Replaces `your-github-username` placeholders in Application manifests before applying them. |
| `GITOPS_PATH` | Local folder containing the GitOps checkout | If `gitops` is beside `infra`, that is the default. In this workspace it is `D:\Projects\devops\zenpharma\gitops` (or `/mnt/d/Projects/devops/zenpharma/gitops` in WSL). | Lets the script read `argocd/apps/<env>/` and the selected manifest files. This folder is required for deployment. |

Environment variables skip prompts and are used as supplied.

## Choose services and run the script

From the `infra` repository root:

```bash
python3 scripts/05_deploy_services.py
```

Choose:

- `F` — frontend only;
- `B` — all backend services;
- `A` — all services; or
- a number from `1` to `9` — one service.

The available Application manifests are:

| Menu number | Service | Manifest |
|---|---|---|
| 1 | `pharma-ui` | `pharma-ui-app.yaml` |
| 2 | `auth-service` | `auth-service-app.yaml` |
| 3 | `drug-catalog-service` | `catalog-service-app.yaml` |
| 4 | `inventory-service` | `inventory-service-app.yaml` |
| 5 | `supplier-service` | `supplier-service-app.yaml` |
| 6 | `manufacturing-service` | `manufacturing-service-app.yaml` |
| 7 | `notification-service` | `notification-service-app.yaml` |
| 8 | `qc-service` | `qc-service-app.yaml` |
| 9 | `api-gateway` | `api-gateway-app.yaml` |

The script applies all-services selections in the order shown: frontend first,
then backends. Check the displayed manifest paths and confirm before applying.

## What happens

1. Checks for `kubectl`, reads the selected environment and local GitOps path,
   and checks that `argocd/apps/<env>/` exists.
2. Shows which selected manifests exist. After confirmation, replaces
   `your-github-username` placeholders and applies each existing manifest.
3. Warns and skips a missing individual manifest. If none of the selected
   manifests can be applied, it exits with an error.
4. Checks Argo CD Application status every 15 seconds for up to ten minutes.
   It reports an application as ready when it is both `Synced` and `Healthy`.
5. Prints an available `pharma-ui` Ingress hostname and a deployment summary.

The wait can time out while Argo CD continues syncing. Ctrl+C also stops only
the monitoring; it does not cancel Argo CD's work. The script's summary may
show an app as still syncing or degraded without treating that wait outcome as
a fatal script error.

## Result and next step

Before assuming a service is deployed, check that its Argo CD Application is
`Synced` and `Healthy`. If it is not, inspect the Application and workload:

```bash
kubectl get applications -n argocd
kubectl get pods -n <env>
```

Replace `<env>` with the selected environment. When the deployment has settled,
run [script 06](./06_verify_deployment.md) for the post-deployment checks.
