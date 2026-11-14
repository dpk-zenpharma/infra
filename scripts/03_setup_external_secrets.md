# Connect External Secrets to AWS Secrets Manager

This guide explains how `03_setup_external_secrets.py` lets applications use
AWS secrets safely, what must be ready first, and where to find the required
values.

## The big picture

Script 01 installs External Secrets Operator (ESO) in the cluster. This script
connects ESO to AWS Secrets Manager and tells it which values to copy into
Kubernetes Secrets for the selected environment.

```text
Terraform creates AWS IAM role and secret values
                     |
                     v
01 installs External Secrets Operator
                     |
                     v
03 gives ESO AWS identity and secret-copy instructions
                     |
                     v
ESO creates Kubernetes Secrets for application pods
```

The application pods read Kubernetes Secrets; they do not need AWS access keys
or the raw secret values in Git manifests.

## What this script sets up, and why

| Item | Why it is needed | What the script does |
|---|---|---|
| IAM Roles for Service Accounts (IRSA) | ESO needs AWS permission to read Secrets Manager without storing long-lived AWS keys in Kubernetes. | Annotates the ESO service account with the Terraform-created IAM role ARN and restarts the operator. |
| `ClusterSecretStore` | ESO needs to know which AWS service and region to use and which service account supplies its AWS identity. | Creates the shared `aws-secrets-manager` connection. |
| `ExternalSecret` resources | ESO needs instructions for which AWS secret fields to copy and what Kubernetes Secret keys to create. | Creates `db-credentials` and `jwt-secret` sync instructions in the selected environment namespace. |

## Before you start

1. Complete [script 01](./01_install_prerequisites.md). ESO and its Kubernetes
   custom resource definitions (CRDs) must be installed.
2. Terraform must have created the EKS OIDC provider and ESO IAM role. The
   role must trust the ESO service account and allow reading the required
   Secrets Manager values.
3. Create the Secrets Manager values for the target environment in the same
   AWS account and region. The script expects:

   | Secrets Manager name | Required JSON properties |
   |---|---|
   | `/pharma/<env>/db-credentials` | `username`, `password`, `host` |
   | `/pharma/<env>/jwt-secret` | `secret` |

   Replace `<env>` with `dev`, `qa`, or `prod`. Use the actual database
   credentials and JWT value for that environment. Do not put secret values in
   this guide, shell history, or Git.
4. Connect `kubectl` to the intended EKS cluster. The script changes resources
   in that cluster and does not change your context.
5. Python 3 and `kubectl` must be available. The script checks for `kubectl`
   using `which`; on Windows, use WSL.

The script checks for `kubectl`, but does not validate the AWS role, its
permissions, account, region, or the secret values before applying resources.

## Values to provide

| Value | What to enter | Where to get it | Why this script needs it |
|---|---|---|---|
| `ENV` | `dev`, `qa`, or `prod` | Select the environment whose secrets and applications should be configured. | Selects the Kubernetes namespace and the `/pharma/<env>/...` secret paths. |
| `AWS_REGION` | Region where the Secrets Manager values are stored | Check the AWS region used for the environment. The default is `us-east-1`. | Configures the `ClusterSecretStore` to read secrets from the correct region. |
| `AWS_ACCOUNT_ID` | The 12-digit AWS account ID | Run `aws sts get-caller-identity --query Account --output text`, or check the AWS Console account menu. | Combined with the role name to build the full IAM role ARN. Make sure it is the account containing the EKS cluster and secrets. |
| `ESO_ROLE_NAME` | Terraform-created ESO IAM role name | Find it in **AWS Console > IAM > Roles**. The expected pattern is `pharma-<env>-eso-role`. | The script combines it with the account ID to construct the ARN that it attaches to the ESO service account. |

The script builds the role ARN as
`arn:aws:iam::<AWS_ACCOUNT_ID>:role/<ESO_ROLE_NAME>`. Defaults are supplied for
dev; confirm or change them for another environment. Environment variables
skip prompts and are used as supplied.

## Run it

From the `infra` repository root:

```bash
python3 scripts/03_setup_external_secrets.py
```

Select the environment, review the account, region, and role ARN, then enter
`Y` or press Enter to continue. Any other response cancels before applying the
resources.

## What happens

1. Creates the selected environment namespace if it does not exist.
2. Adds the IAM role ARN to the ESO service account in namespace
   `external-secrets`, then restarts the operator so it uses that identity.
3. Waits for ESO's secret resource types to be ready and creates the
   cluster-wide `aws-secrets-manager` store.
4. Creates two secret-sync instructions in the selected environment:
   - `db-credentials` copies `username`, `password`, and `host` from
     `/pharma/<env>/db-credentials` into application keys including
     `DB_USERNAME`, `DB_PASSWORD`, `DB_HOST`, and Spring datasource keys.
   - `jwt-secret` copies `secret` from `/pharma/<env>/jwt-secret` into
     `JWT_SECRET`.
5. Waits up to 90 seconds for both values to synchronize and prints their
   status. The actual secret values are not printed.

ESO refreshes the generated Kubernetes Secrets hourly. The resulting Kubernetes
Secrets are named `db-credentials` and `jwt-secret` in the selected namespace.

## Result and next step

Before deploying applications, confirm that both `ExternalSecret` resources
show Ready/Synced. The script can print `External Secrets setup complete` even
when its wait ends without both secrets syncing; a warning means this
prerequisite is **not ready**.

If synchronization fails, check that the secret names and JSON property names
match, that the selected region/account are correct, and that the IAM role has
`secretsmanager:GetSecretValue` permission and trusts the ESO service account.
Inspect a resource with:

```bash
kubectl describe externalsecret db-credentials -n <env>
```

Replace `<env>` with the selected environment. After the secrets are ready,
continue with [script 04](./04_run_pipeline.md). Scripts 02, 03, and 04 all
need to be complete before [script 05](./05_deploy_services.md).
