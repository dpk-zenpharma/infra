# Build and publish application images

This guide explains how `04_run_pipeline.py` starts the GitHub Actions
workflows that build application images, what you need first, and how to check
the results.

## The big picture

This script does not build the applications on your computer. It asks GitHub
Actions to run the selected workflow in the source repository. The workflows
build and scan the code, push container images to Amazon ECR, and update the
image tags in the GitOps repository.

```text
Choose services and branch
          |
          v
04 asks GitHub Actions to run the workflows
          |
          v
Workflows build images, push to ECR, and update GitOps tags
          |
          v
05 applies Argo CD Applications to deploy those images
```

## What this script does, and why

| Item | Why it is needed | What the script does |
|---|---|---|
| GitHub CLI (`gh`) | The script uses GitHub's command-line interface to dispatch workflows and monitor their runs. | Checks that `gh` is installed and authenticated, starts the selected workflows, and reports their results. |
| Workflow selection | Each application has a GitHub Actions workflow in either the frontend or backend repository. | Lets you build the frontend, all backend services, all services, or one numbered service. |
| Branch/ref | GitHub needs to know which source revision to build. | Passes the selected branch to each workflow dispatch. |

## Before you start

1. The source repositories and their GitHub Actions workflows must exist. The
   workflows must support manual `workflow_dispatch`.
2. GitHub Actions must already be configured with the AWS/ECR permissions and
   GitOps access required by the workflows. This local script only starts and
   monitors them; it does not configure their credentials.
3. Install GitHub CLI (`gh`) and authenticate:

   ```bash
   gh auth login
   gh auth status
   ```

   Your GitHub account needs permission to dispatch the workflows and view
   their runs.
4. Complete scripts 02 and 03 as part of the recommended setup sequence. The
   image build itself does not directly require them, but script 05 needs the
   Argo CD setup, secrets, and successful images.
5. Python 3 and `gh` must be available in the environment where you run the
   script. It checks for `gh` using `which`; on Windows, use WSL.

## Values to provide

| Value | What to enter | Where to get it | Why this script needs it |
|---|---|---|---|
| `GITHUB_ORG` | GitHub username or organization that owns the source repositories | Check the repository URL in GitHub. Default: `zenpharma`. | Together with the repository name, identifies the repository where the workflow runs. |
| `FRONTEND_REPO` | Repository containing `pharma-ui` | Check the frontend repository name in GitHub. Default: `frontend`. | Selects the repository for the frontend workflow. |
| `BACKEND_REPO` | Repository containing the backend services | Check the backend repository name in GitHub. Default: `backend`. | Selects the repository for the backend workflows. |
| `BRANCH` | Branch or ref to build | Choose the branch containing the code you want to release. Default: `develop`. | Tells GitHub Actions which source revision to build. |

Set these as environment variables to skip their prompts. The service selection
is made interactively when the script runs.

## Run it and choose what to build

From the `infra` repository root:

```bash
python3 scripts/04_run_pipeline.py
```

Choose one option:

- `F` — frontend only (`pharma-ui`);
- `B` — all eight backend services;
- `A` — frontend and all backend services; or
- a number from `1` to `9` — one service.

Review the owner, repository, branch, and selected workflows before confirming.
The script asks for confirmation before triggering GitHub Actions.

| Menu number | Service | Workflow file |
|---|---|---|
| 1 | `pharma-ui` | `ci-pharma-ui.yml` (frontend repository) |
| 2 | `auth-service` | `ci-auth-service.yml` (backend repository) |
| 3 | `drug-catalog-service` | `ci-drug-catalog.yml` (backend repository) |
| 4 | `inventory-service` | `ci-inventory-service.yml` (backend repository) |
| 5 | `supplier-service` | `ci-supplier-service.yml` (backend repository) |
| 6 | `manufacturing-service` | `ci-manufacturing-service.yml` (backend repository) |
| 7 | `notification-service` | `ci-notification.yml` (backend repository) |
| 8 | `qc-service` | `ci-qc-service.yml` (backend repository) |
| 9 | `api-gateway` | `ci-api-gateway.yml` (backend repository) |

## What happens after you confirm

1. The script dispatches one GitHub Actions workflow per selected service.
2. It tries to find each run and checks its status every 30 seconds, for up to
   30 minutes.
3. It prints a run link and final outcome when available.

If triggering a particular workflow fails, it warns and continues with the
other selections. The script exits with an error if no workflow could be
started or if a completed run failed. A timeout does not cancel a run. Pressing
Ctrl+C only stops watching; workflows continue running in GitHub.

## Result and next step

Before deploying, confirm that every selected workflow completed successfully.
The workflows—not this script—push images to ECR and update image tags in
GitOps. If a workflow fails or times out, open its GitHub Actions run link and
check the logs and final status.

When the image builds succeeded and their GitOps tags are updated, continue
with [script 05](./05_deploy_services.md).
