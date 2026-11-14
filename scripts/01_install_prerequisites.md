# Install the Kubernetes platform components

This guide explains what `01_install_prerequisites.py` does, what you need
before running it, and where to find the values it asks for.

## The big picture

Terraform creates the AWS resources and the EKS cluster. This installer then
connects to that existing cluster and installs three platform components that
the applications will need later:

```text
Terraform creates AWS infrastructure and the EKS cluster
                         |
                         v
01_install_prerequisites.py installs cluster components
             /           |            \
            v            v             v
     Load Balancer     Argo CD     External Secrets
      Controller                    Operator
                         |
                         v
02_bootstrap_argocd.py and 03_setup_external_secrets.py configure them
                         |
                         v
04_run_pipeline.py builds and publishes application images
                         |
                         v
05_deploy_services.py deploys the applications
                         |
                         v
06_verify_deployment.py checks the result
```

In short: Terraform creates the place where Kubernetes runs; this script installs
the tools inside that place. It does not create the cluster or deploy the
application services.

## What gets installed, and why

| Component | Why it is needed | What this script does |
|---|---|---|
| AWS Load Balancer Controller | Converts Kubernetes Ingress resources into AWS load balancers, so deployed services can be reached from outside the cluster. | Installs the controller in `kube-system` and gives it the cluster, VPC, region, and IAM role details it needs to manage load balancers. |
| Argo CD | Reads deployment configuration from Git and keeps the cluster in sync with it. | Installs Argo CD in `argocd` and prints its initial admin password. Registering the Git repository and creating Argo CD projects happen in script 02. |
| External Secrets Operator (ESO) | Lets applications use selected values from AWS Secrets Manager as Kubernetes Secrets, without putting the secret values in Git. | Installs ESO and its Kubernetes resource definitions in `external-secrets`. Giving ESO AWS access and telling it which secrets to copy happen in script 03. |

These components are installed with Helm. Re-running the script upgrades the
existing Helm releases rather than creating duplicate releases.

### Does applying an Ingress create the load balancer automatically?

**Yes, when the Ingress is configured for the AWS Load Balancer Controller.**
After an Ingress with class `alb` is applied to the cluster (in this project,
Argo CD applies it from the GitOps configuration), the running controller
notices it and asks AWS to create and configure the ALB. This happens
automatically; you do not separately create the application's ALB in the AWS
Console or with Terraform.

It is not triggered by just any Ingress. The controller must be installed and
running, its IAM role must allow it to manage load balancers, and the Ingress
must have valid settings and a working service backend. AWS must also have
suitable subnets for the requested load balancer type. For example, this
project's public ALB settings require correctly tagged public subnets. If a
requirement is missing, the controller cannot finish creating the ALB; check
the Ingress events and controller logs for the error.

## Before you start

Make sure all of these are true:

1. **Terraform has finished successfully** for the environment you want to use.
   The EKS cluster, its network, and the IAM role for the Load Balancer
   Controller must already exist.
2. **You are using the right AWS account and environment.** Check your AWS
   identity before running the installer:

   ```bash
   aws sts get-caller-identity
   ```

3. **The required command-line tools are installed:** Python 3, `aws`,
   `kubectl`, and `helm`. The script also calls `which` to check for them.
4. **You can reach the cluster.** Your AWS identity must be allowed to describe
   the EKS cluster and update kubeconfig. Your Kubernetes identity must be
   allowed to install Helm releases and apply Kubernetes resources.
5. **On Windows, run from WSL** (or another Linux-like environment with
   `which`, Python, AWS CLI, `kubectl`, and Helm available). A regular Windows
   terminal may not provide the `which` command the script uses.

The GitOps repository is optional for this script. If you have it locally, the
installer can use two optional files from it (described below).

## Find the values the installer asks for

The installer prompts for the cluster name, AWS region, Load Balancer
Controller's IAM role ARN, and local GitOps path. It normally finds the VPC ID
from AWS automatically.

| Value | What to enter | Where to get it | Why this script needs it |
|---|---|---|---|
| `CLUSTER_NAME` | The name of the EKS cluster Terraform created. | If Terraform is initialized and its state is available, run `terraform -chdir=envs/dev output eks_cluster_name` from the `infra` repository. The dev cluster in this project is `pharma-dev-cluster`. You can also find the name in **AWS Console > EKS > Clusters**. | To connect `kubectl` to the intended EKS cluster and tell the Load Balancer Controller which cluster it manages. |
| `AWS_REGION` | The AWS region containing that cluster. The dev default is `us-east-1`. | Use the region selected for the Terraform environment and confirm it in **AWS Console > EKS > Clusters**. The region must match the cluster. | To find the EKS cluster and VPC in AWS, and to configure the controller to manage load balancers in the correct region. |
| `VPC_ID` | The VPC that contains the EKS cluster. | Normally leave this unset: the script asks AWS for it using the cluster name and region. If that lookup fails, find the cluster's VPC in **AWS Console > EKS > Clusters > [cluster] > Networking**, or run the command below. | To tell the Load Balancer Controller which VPC contains the cluster, so it can find suitable subnets when creating an ALB. |
| `ALB_CONTROLLER_ROLE` | The full ARN of the IAM role for the AWS Load Balancer Controller. | Terraform creates this role. For dev, its role name is `pharma-dev-alb-controller-role`. Find the full ARN in **AWS Console > IAM > Roles**, or run the command below. Make sure the role belongs to the same AWS account and environment as the cluster. | To let the controller use its assigned AWS permissions to create and manage load balancers. |
| `GITOPS_PATH` | The local folder containing your GitOps repository. | If the `gitops` repository is checked out beside `infra`, that is the default. Otherwise enter its local folder path. You can leave the default if you do not have a checkout; the optional GitOps files will be skipped. | To locate optional ALB settings and the optional Argo CD Ingress manifest. If the repository or files are absent, the installer skips those optional settings. |

### What the optional GitOps files do

The installer checks for two files under `GITOPS_PATH`. Neither file is required
for the installer to install the three platform components.

#### `k8s/ingress/alb-controller-values.yaml`

This would contain additional Helm settings for the AWS Load Balancer
Controller itself. If the file exists, the installer includes it in the first
Helm install/upgrade. In the GitOps checkout checked for this setup, this file
is **not present**, so the installer skips it and uses the settings passed
directly in the script (cluster name, AWS region, VPC ID, and IAM role). The
installer's later Helm upgrade also does not include this optional file.

#### `argocd/install/argocd-ingress.yaml`

This file is **present** in the GitOps checkout. After installing Argo CD, the
script applies it to the cluster. It creates a Kubernetes `Ingress` that asks
the AWS Load Balancer Controller to expose the `argocd-server` web UI through
an internet-facing Application Load Balancer (ALB), using HTTPS on port 443.
The controller then asks AWS to create and configure the ALB; you do not create
that ALB separately in Terraform or the AWS Console.

The hostname in the file is `argocd.pharma.internal`. The Ingress file does
**not** create a DNS record, so that name must be made to resolve to the ALB
before users can reach the UI by hostname. It also does not specify an ACM
certificate ARN; a matching certificate must be available for the HTTPS
listener. If DNS or certificate setup is not ready, the ALB may still be
created, but hostname access or HTTPS may not work as intended. You can still
access Argo CD with the `kubectl port-forward` command printed by the installer.

To look up the VPC ID manually:

```bash
aws eks describe-cluster \
  --name pharma-dev-cluster \
  --region us-east-1 \
  --query 'cluster.resourcesVpcConfig.vpcId' \
  --output text
```

To look up the dev role ARN:

```bash
aws iam get-role \
  --role-name pharma-dev-alb-controller-role \
  --query 'Role.Arn' \
  --output text
```

For QA or production, use that environment's cluster, region, and role name
instead of the dev examples. The role ARN is important: the controller uses the
role to call AWS APIs. Do not rely on the installer's prefilled role ARN unless
you have confirmed that it is the role created for your AWS account and
environment.

If you set a value as an environment variable, the installer skips its prompt.
For example, in WSL:

```bash
export CLUSTER_NAME="pharma-dev-cluster"
export AWS_REGION="us-east-1"
export ALB_CONTROLLER_ROLE="arn:aws:iam::<account-id>:role/pharma-dev-alb-controller-role"
# Optional: set these only if needed.
export GITOPS_PATH="/path/to/gitops"
# export VPC_ID="vpc-0123456789abcdef0"

python3 scripts/01_install_prerequisites.py
```

Replace `<account-id>` with the AWS account ID for the role. Values supplied
through environment variables are used as-is; the script does not check that
they match one another.

## Run the installer

From the `infra` repository root in WSL:

```bash
python3 scripts/01_install_prerequisites.py
```

The script checks for its tools, asks for any values not already supplied, and
then shows a configuration summary. **Check the cluster, region, VPC ID, and
role ARN before confirming.** Enter `Y` or press Enter to continue. Any other
answer cancels the installation.

## What it does, step by step

1. Checks that `kubectl`, `helm`, and `aws` are available.
2. Collects the cluster, region, role, and GitOps path. If `VPC_ID` is not set,
   it asks AWS for the VPC attached to the EKS cluster. If that lookup fails, it
   asks you to enter the VPC ID.
3. Shows the selected settings and waits for your confirmation.
4. Runs `aws eks update-kubeconfig` so `kubectl` can connect to the selected
   cluster, then prints the current Kubernetes context. If updating kubeconfig
   fails, the script warns and continues with the context already configured.
   **If the update fails or the printed context is not the intended cluster,
   interrupt the script immediately (Ctrl+C); it will otherwise continue with
   cluster changes.**
5. Adds or refreshes the Helm chart repositories used for the three components.
6. Installs or upgrades the AWS Load Balancer Controller. If the optional file
   `k8s/ingress/alb-controller-values.yaml` exists under `GITOPS_PATH`, the
   first Helm install/upgrade uses it. The installer then refreshes the
   controller's webhook configurations/certificates with a second upgrade; that
   second command does not pass the optional values file.
7. Installs or upgrades Argo CD. It prints the initial `admin` password and a
   command for opening the UI through a local port-forward. If
   `argocd/install/argocd-ingress.yaml` exists under `GITOPS_PATH`, it applies
   that file too.
8. Installs or upgrades External Secrets Operator, including the custom
   resource definitions needed by later secret-sync resources.
9. Lists the pods for the three components as a basic check.

## What changes and what does not

This script changes your local AWS kubeconfig, refreshes Helm repository
information, and installs or updates resources in the currently selected
Kubernetes cluster. It also deletes the named AWS Load Balancer Controller
webhook configuration objects, if present, before refreshing them. Confirm the
AWS account and Kubernetes context before allowing it to proceed.

It does **not**:

- create the EKS cluster, VPC, IAM role, or AWS Secrets Manager values;
- connect Argo CD to the GitOps repository or create Argo CD projects;
- configure ESO to access AWS Secrets Manager or create synchronized secrets;
- deploy the application services; or
- create an AWS load balancer immediately. That happens later when an
  appropriate Ingress is deployed.

## When it succeeds

The script ends with `All pre-requisites installed successfully.` and prints
pod status for the controller, Argo CD, and ESO. This confirms that the
installer's commands completed; it is not a full test of application deployment,
Ingress routing, or secret retrieval.

The Argo CD initial admin password is printed in the terminal. Save it in an
approved password manager; do not commit it or share terminal logs containing
it. The port-forward command printed by the script lets you open the UI at
`https://localhost:8080` while the command is running.

Next, run [script 02](./02_bootstrap_argocd.md) and
[script 03](./03_setup_external_secrets.md). They can be run in either order
after this installer. Then run [script 04](./04_run_pipeline.md) to build and
publish the images, [script 05](./05_deploy_services.md) to deploy the
applications, and [script 06](./06_verify_deployment.md) to check the result.
Scripts 02, 03, and 04 must all be complete before script 05. See the
[scripts overview](./README.md) for the full sequence and prerequisites.

## If something goes wrong

- **A tool is not found:** install it in the same WSL environment where you run
  the script, and confirm it is on `PATH`.
- **AWS cannot find the cluster or VPC:** check the AWS account, region, and
  cluster name. Confirm Terraform completed for that environment.
- **Kubeconfig update fails or the context looks wrong:** check AWS credentials
  and cluster access. The script continues after an update failure, so verify
  the printed context before allowing any installation.
- **The role ARN is wrong or the controller cannot manage load balancers:**
  retrieve the ARN from IAM and check that Terraform created the role for this
  cluster and environment.
- **A Helm install times out or pods are not ready:** verify the cluster
  context, AWS credentials, network access, IAM role, and available EKS node
  capacity. Use `kubectl get pods -n kube-system`, `kubectl get pods -n argocd`,
  or `kubectl get pods -n external-secrets` to inspect the relevant component.
