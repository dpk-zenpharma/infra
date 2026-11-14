# Connect Argo CD to the GitOps repository

This guide explains what `02_bootstrap_argocd.py` configures, what you need
before running it, and how to continue afterward.

## The big picture

Script 01 installs Argo CD in the EKS cluster. This script gives Argo CD access
to the GitOps repository and creates an Argo CD project that controls which
repository and cluster namespaces its applications may use.

```text
01 installs Argo CD
        |
        v
02 gives Argo CD Git repository access and creates its project
        |
        +--------------------------+
        |                          |
03 configures secret access   04 builds/publishes images
        |                          |
        +-------------+------------+
                      v
              05 deploys applications
```

This script does **not** create or deploy the service applications. Script 05
does that after scripts 02, 03, and 04 have completed.

## What this script sets up, and why

| What is being set up | Why Argo CD needs it | What this script does |
|---|---|---|
| Login details for the GitOps repository | The deployment files are stored in GitHub. Argo CD needs a username and token to read them, especially if the repository is private. | Saves the repository URL, GitHub username, and PAT in a Kubernetes Secret in the `argocd` namespace, then marks it as repository credentials. This lets Argo CD authenticate to GitHub; it does not copy or deploy the applications yet. |
| The `pharma` project in Argo CD | The project is a set of rules for Argo CD applications: which Git repository they may use and which Kubernetes namespaces they may deploy into. | Applies `argocd/projects/pharma-project.yaml` from your local GitOps folder. If that file is missing, the script creates a built-in project with the repository and environment rules instead. |

## Before you start

1. Complete [script 01](./01_install_prerequisites.md). Argo CD must already be
   installed in the cluster.
2. Make sure `kubectl` is connected to the intended EKS cluster. This script
   does not change your Kubernetes context.
3. Have a GitHub Personal Access Token (PAT) that can read the GitOps
   repository. You need repository read access; the token is entered hidden
   when prompted.
4. Python 3 and `kubectl` must be available in the environment where you run
   the script. It checks for `kubectl` using `which`; on Windows, use WSL.

## Values to provide

| Value | What to enter | Where to get it | Why this script needs it |
|---|---|---|---|
| `ENV` | `dev`, `qa`, or `prod` | Choose the environment you are preparing. | The script displays this environment in its summary. The created project permits all three environments. |
| `GITOPS_REPO_URL` | HTTPS URL of the GitOps repository | Use the repository URL in GitHub; the default is `https://github.com/zenpharma/gitops.git`. | Argo CD uses this URL to find the repository it should read. |
| `GITHUB_USERNAME` | Your personal GitHub username | Use your GitHub account username, not the organization name. | The repository credential uses this username with the PAT. It also replaces the `your-github-username` placeholder in the optional project manifest. |
| `GITOPS_TOKEN` | PAT with read access to the GitOps repository | Create/use a token authorized to read that repository. Enter it at the hidden prompt. | Argo CD uses it to authenticate when reading a private repository. |
| `GITOPS_PATH` | Local folder containing your GitOps checkout | If `gitops` is beside `infra`, that is the default. In this workspace it is `D:\Projects\devops\zenpharma\gitops` (or `/mnt/d/Projects/devops/zenpharma/gitops` in WSL). | The script looks here for `argocd/projects/pharma-project.yaml`. If not found, it uses an inline fallback project. |

You can set these as environment variables to skip prompts. A token entered at
the prompt is hidden and is not printed in the summary. Avoid putting tokens in
shell history or sharing logs that could contain credentials.

## Run it

From the `infra` repository root:

```bash
python3 scripts/02_bootstrap_argocd.py
```

Review the repository URL and environment, then enter `Y` or press Enter to
continue. Any other response cancels before the Kubernetes resources are
written.

## What happens

1. Checks that `kubectl` is installed and that the `argocd-server` Deployment
   exists in namespace `argocd`.
2. Creates or updates the `gitops-repo` credential Secret and labels it as an
   Argo CD repository.
3. Applies `argocd/projects/pharma-project.yaml` from the local GitOps checkout
   if it exists. Otherwise, creates a built-in `pharma` project that allows the
   configured repository and the `dev`, `qa`, and `prod` namespaces.
4. Prints the Argo CD port-forward command for opening the UI at
   `https://localhost:8080`.

The fallback project allows all namespaced resource kinds and the Namespace
cluster resource. If the local project YAML is used, inspect its permissions
to confirm they are appropriate for your cluster.

## Result and next step

After success, Argo CD has repository credentials and a `pharma` project. This
is configuration only; application definitions and workloads are added later.
If the repository or project cannot be applied, treat the setup as incomplete.

Run [script 03](./03_setup_external_secrets.md) and
[script 04](./04_run_pipeline.md) next. They can run in either order after
scripts 01 and 02. Complete scripts 02, 03, and 04 before running
[script 05](./05_deploy_services.md).
