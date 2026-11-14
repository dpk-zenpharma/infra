# IAM Module

This module creates the AWS identity and access layer required by the project.

It is one of the most important modules because it connects:

- GitHub Actions
- Kubernetes workloads
- ArgoCD
- External Secrets Operator
- AWS Load Balancer Controller

### How the AWS Load Balancer is created in this project

There is no Terraform module in this repository that directly creates the application's AWS Application Load Balancer (ALB). These parts work together:

1. **EKS provides the Kubernetes cluster and worker nodes.** The EKS infrastructure is defined in the [EKS module](../eks/main.tf).
2. **This IAM module gives the controller permission to manage load balancers in AWS.** It creates the `pharma-<env>-alb-controller-role` role and its policy. The role trusts the EKS service account `kube-system/aws-load-balancer-controller`, so the controller can use temporary AWS credentials instead of stored access keys. See the [controller role and policy](./main.tf).
3. **The prerequisites script installs the AWS Load Balancer Controller into the cluster.** It uses Helm and runs the controller in the Kubernetes `kube-system` namespace. See [scripts/01_install_prerequisites.py](../../scripts/01_install_prerequisites.py).
4. **A Kubernetes `Ingress` asks for an ALB.** The controller watches Ingress resources configured with `ingressClassName: alb`. When it finds one, it uses its IAM role to create and manage the corresponding ALB and related AWS resources. The ALB is therefore created dynamically by the controller, not directly by a Terraform module.

In short: **EKS runs the controller, IAM authorizes it, the setup script installs it, and a Kubernetes Ingress causes it to create an ALB.** The IAM role alone does not create a load balancer; an applicable Ingress must be deployed.

The module uses AWS IAM roles, OIDC trust policies, and service account identity mapping.

---

## 1) Why IAM is needed here

Without IAM, workloads and automation would need static AWS credentials stored in secrets or environment variables. That is risky and not recommended.

This repo uses AWS IAM roles for service accounts (IRSA) and OIDC for GitHub Actions.

That means:

- A pod running under an authorized Kubernetes service account can get temporary AWS credentials. Those credentials let it perform only the AWS actions allowed by its assigned IAM role—for example, the External Secrets Operator can read the secrets it is permitted to access.
- GitHub Actions can deploy infrastructure without static access keys
- AWS resources are accessible in a short-lived, tightly scoped way

In AWS terminology, **“assume a role”** means “temporarily use the permissions of that role.” The pod does not become an IAM role permanently, and it does not receive the role's password; AWS issues temporary credentials after checking the pod's identity.

---

## 2) Files in this module

- [main.tf](./main.tf)
- [variables.tf](./variables.tf)
- [outputs.tf](./outputs.tf)
- [github-actions-oidc.tf](./github-actions-oidc.tf)

---

## 3) Main IAM concepts used

### 3.1 OIDC federation

OIDC lets an external system exchange a token for temporary AWS credentials.

This repo uses:

- GitHub Actions OIDC
- EKS OIDC provider for IRSA

The EKS module exposes the OIDC provider ARN and issuer URL in [modules/eks/outputs.tf](../eks/outputs.tf):

```hcl
output "oidc_provider_arn" {
  description = "ARN of the OIDC Provider for IRSA"
  value       = module.eks.oidc_provider_arn
}

output "cluster_oidc_issuer_url" {
  description = "URL of the OIDC Provider for IRSA"
  value       = module.eks.cluster_oidc_issuer_url
}
```

The environment passes these two outputs into this IAM module in [envs/dev/main.tf](../../envs/dev/main.tf):

```hcl
oidc_provider_arn = module.eks.oidc_provider_arn
oidc_provider_url = module.eks.cluster_oidc_issuer_url
```

The IAM trust policies use the ARN to identify the trusted EKS OIDC provider, and the URL to build conditions that restrict which Kubernetes service account may use each role.

---

## 4) External Secrets Operator (ESO) role

The first important section in [main.tf](./main.tf) is:

```hcl
data "aws_iam_policy_document" "eso_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:external-secrets:external-secrets"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }

    principals {
      identifiers = [var.oidc_provider_arn]
      type        = "Federated"
    }
  }
}
```

**What this does:** `data "aws_iam_policy_document"` builds a JSON trust policy for the IAM role; it does not create the role or grant access to Secrets Manager by itself. The role uses this policy to decide **who may assume it**:

- `principals` identifies this EKS cluster's OIDC provider (`var.oidc_provider_arn`) as a trusted identity source. The ESO Helm install creates the `external-secrets` service account inside the `external-secrets` namespace.

  They are different Kubernetes objects:
  - the namespace groups resources,
  - while the service account is the identity ESO's pod uses.

  The setup script annotates the service account with this IAM role. When the ESO pod runs using that account, Kubernetes provides it with a short-lived service-account token for AWS STS.

  - AWS STS (Security Token Service) is the AWS service that issues temporary credentials to an identity that is allowed to assume an IAM role. In this setup, the ESO pod presents its Kubernetes service-account token to STS; if the role’s trust conditions match, STS returns temporary credentials ESO can use to read Secrets Manager.

  Terraform configures AWS to trust the cluster's OIDC provider; it does not create the token.

- `actions` allows the web-identity sign-in action, `sts:AssumeRoleWithWebIdentity`.

  `sts:AssumeRoleWithWebIdentity` allows the ESO pod to ask AWS STS to exchange its Kubernetes token for temporary AWS credentials for this IAM role.

  In this setup: ESO presents its token → STS checks the trusted EKS issuer and the sub/aud conditions → if they match, STS returns temporary credentials. This action only allows ESO to assume the role; the role’s separate permissions policy determines what ESO can do afterward, such as read Secrets Manager secrets.
- `sub` means **subject**:  identifies who the token is for. Here it must be system:serviceaccount:external-secrets:external-secrets—the external-secrets service account in the external-secrets namespace.
- `aud` means **audience**: which service the token is intended for. This policy requires `sts.amazonaws.com`, because AWS Security Token Service (STS) is the service that exchanges the EKS OIDC token for temporary AWS credentials.

Note: `aud` says who the token is intended for—here, AWS STS, which performs the exchange. `sub` identifies who is requesting access—the ESO service account in the `external-secrets` namespace. STS checks both before issuing temporary credentials.
- Both conditions use `StringEquals`, so both token values must match exactly for STS to allow the role assumption. The condition keys are scoped to this cluster's OIDC provider.
- `replace(..., "https://", "")` removes the URL scheme because OIDC token claims use the provider URL without `https://` as the condition key.

In effect, **only a pod using that specific service account in this EKS cluster can request this role through OIDC**. This is the role's trust/identity check—not its AWS permissions. The separate policy below grants the role permission to read the project's Secrets Manager secrets.

**When does ESO fetch a secret?** The setup script creates Kubernetes `ExternalSecret` resources that tell ESO which AWS secrets to copy. For example, the dev `db-credentials` resource points to `/pharma/dev/db-credentials`, and `jwt-secret` points to `/pharma/dev/jwt-secret`. When ESO sees these resources, it reads the requested values from AWS Secrets Manager and creates corresponding Kubernetes Secrets. Each resource has `refreshInterval: 1h`, so ESO checks for updates hourly as well as performing its initial sync.

**When the token is used:** To perform that read, the ESO pod presents its projected service-account token to AWS STS and requests `sts:AssumeRoleWithWebIdentity`. STS checks that the token is from the trusted EKS OIDC issuer and that its `sub` and `aud` claims match the conditions above. If they do, STS returns temporary credentials for `pharma-dev-eso-role`; ESO uses those credentials to read the requested values from Secrets Manager. The token proves the pod's Kubernetes identity; the temporary credentials let it make the AWS calls allowed by the role's separate permissions policy. Application pods then use the Kubernetes Secrets ESO created.

### How this role connects to the setup scripts

This section of `main.tf` configures **AWS-side permissions and trust**. It does not install ESO or configure Kubernetes by itself. These are separate steps in the project:

1. **Terraform creates the IAM role and its permissions.** The role is created by the `resource "aws_iam_role" "eso_role"` block in [modules/iam/main.tf](./main.tf#L26-L35). Its `name` is built from `"${var.project}-${var.env}-eso-role"`. The dev environment passes `project = "pharma"` and `env = "dev"` through the `module "iam"` block in [envs/dev/main.tf](../../envs/dev/main.tf#L68-L76), so Terraform creates an AWS IAM role named **`pharma-dev-eso-role`**. The `assume_role_policy` connects that role to the EKS OIDC provider and allows the `external-secrets` Kubernetes service account in the `external-secrets` namespace to use it. A separate policy, attached to this role below, allows `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret` for secrets under `/pharma/*`.

    Note:
    Those are two allowed AWS actions in the permissions policy—not two separate policies:

    - `secretsmanager:GetSecretValue` lets ESO retrieve the secret’s actual value, such as the database password.
    - `secretsmanager:DescribeSecret` lets ESO retrieve information about a secret, such as its name, ARN, and status.

    Together, they let ESO find and read the Secrets Manager secrets covered by the policy’s /pharma/* resource scope.

2. **The prerequisites script installs ESO.** [scripts/01_install_prerequisites.py](../../scripts/01_install_prerequisites.py) installs the ESO controller with Helm in the `external-secrets` namespace. The Helm chart creates the Kubernetes service account named `external-secrets` for the controller to use.
3. **The ESO setup script connects the controller to the role.** [scripts/03_setup_external_secrets.py](../../scripts/03_setup_external_secrets.py) builds the role ARN from the AWS account ID and role name, then annotates the `external-secrets` Kubernetes service account with `eks.amazonaws.com/role-arn=<role ARN>`. It restarts the controller so its pods use the service account and updated role annotation.
4. **That same setup script tells ESO what to read from AWS.** It creates a `ClusterSecretStore` that selects AWS Secrets Manager, the region, and the `external-secrets` service account. It also creates `ExternalSecret` resources that name the AWS secret paths and map JSON fields into Kubernetes Secrets.

**Where to see the service account:** run these commands against the EKS cluster after the scripts have completed:

```bash
kubectl get serviceaccount external-secrets -n external-secrets
kubectl describe serviceaccount external-secrets -n external-secrets
```

The first confirms it exists; the second shows its details, including the IAM role annotation added by the ESO setup script.

The relationship is:

```text
Terraform IAM role + read policy
        | trusts EKS OIDC identity for the external-secrets service account
        v
scripts/03_setup_external_secrets.py annotates that service account with the role ARN
        |
        v
ESO controller pod uses temporary AWS credentials for that role
        |
        v
ESO reads permitted AWS Secrets Manager values and writes Kubernetes Secrets
```

So, Terraform prepares the AWS role and defines **who may use it** and **what that role may read**. `01_install_prerequisites.py` installs ESO. `03_setup_external_secrets.py` links ESO's Kubernetes service account to the role and configures which AWS secrets ESO should synchronize. If any of these pieces is missing, ESO may be installed but unable to read the AWS secrets.

Then the role is created:

```hcl
resource "aws_iam_role" "eso_role" {
  name               = "${var.project}-${var.env}-eso-role"
  assume_role_policy = data.aws_iam_policy_document.eso_assume_role.json
}
```

And the policy attached to it:

```hcl
resource "aws_iam_policy" "eso_secrets_policy" {
  name        = "${var.project}-${var.env}-eso-secrets-policy"
  description = "Allow External Secrets Operator to read pharma secrets from AWS Secrets Manager"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:DescribeSecret"
        ]
        Resource = "arn:aws:secretsmanager:*:${var.aws_account_id}:secret:/pharma/*"
      }
    ]
  })
}
```

### Why this matters

This allows External Secrets Operator to read secret values from AWS Secrets Manager and inject them into the app as Kubernetes secrets.

This is how the project keeps sensitive values such as DB password and JWT secret outside the application manifests.

---

## 5) ArgoCD IRSA role

This section creates a trust policy for ArgoCD:

```hcl
data "aws_iam_policy_document" "argocd_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:argocd:argocd-application-controller"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }

    principals {
      identifiers = [var.oidc_provider_arn]
      type        = "Federated"
    }
  }
}
```

### Purpose

This lets ArgoCD's application controller access AWS resources using a Kubernetes service account identity instead of secret-based credentials.

This is used in a GitOps setup where ArgoCD needs to manage resources or read environment-specific configurations.

---

## 6) AWS Load Balancer Controller role

This role is used by the AWS Load Balancer Controller in Kubernetes.

```hcl
data "aws_iam_policy_document" "alb_controller_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:sub"
      values   = ["system:serviceaccount:kube-system:aws-load-balancer-controller"]
    }

    condition {
      test     = "StringEquals"
      variable = "${replace(var.oidc_provider_url, "https://", "")}:aud"
      values   = ["sts.amazonaws.com"]
    }

    principals {
      identifiers = [var.oidc_provider_arn]
      type        = "Federated"
    }
  }
}
```

Then the corresponding AWS IAM policy is created with permissions like:

- `ec2:DescribeSubnets`
- `ec2:DescribeSecurityGroups`
- `elasticloadbalancing:CreateLoadBalancer`
- `elasticloadbalancing:CreateTargetGroup`
- `elasticloadbalancing:CreateListener`
- `elasticloadbalancing:RegisterTargets`

### Purpose

This allows the controller to create and manage AWS ALBs/NLBs that front the application.

Without this role, the Kubernetes ingress or load balancer controller would not be able to manage AWS load balancers.

---

## 7) GitHub Actions OIDC provider

The separate file [github-actions-oidc.tf](./github-actions-oidc.tf) handles CI/CD identity for GitHub Actions.

```hcl
resource "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = ["sts.amazonaws.com"]

  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}
```

`thumbprint_list` tells AWS which certificate fingerprints to trust when connecting securely to GitHub’s OIDC provider.

The two entries are alternative trusted certificate fingerprints, not two tokens or two permissions. They let AWS validate GitHub’s OIDC endpoint against either certificate in the configured list—helpful if the certificate chain changes—so AWS can keep trusting GitHub during a transition.
### Purpose

This registers GitHub as a trusted OIDC provider for AWS.

This file configures GitHub Actions to access specific AWS services without storing permanent AWS keys in GitHub.

During CI, workflows in the frontend and backend repositories use GitHub’s OIDC token to assume the `pharma-dev-github-actions-role`. The role allows them to push container images to ECR and read EKS cluster information—it does not grant access to Secrets Manager secret values. The trust policy limits which repositories and branches can assume the role.

Then the trust policy restricts which repositories and branches are allowed:

```hcl
data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    effect  = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github_actions.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = [
        "repo:${var.github_org}/frontend:ref:refs/heads/main",
        "repo:${var.github_org}/frontend:ref:refs/heads/develop",
        "repo:${var.github_org}@${var.github_owner_id}/frontend@${var.github_frontend_repository_id}:ref:refs/heads/main",
        "repo:${var.github_org}@${var.github_owner_id}/frontend@${var.github_frontend_repository_id}:ref:refs/heads/develop",
        "repo:${var.github_org}/backend:ref:refs/heads/main",
        "repo:${var.github_org}/backend:ref:refs/heads/develop",
      ]
    }
  }
}
```

Note:
- Yes we can see this `aws_iam_openid_connect_provider.github_actions` in AWS. In the AWS Console, open IAM → Identity providers and look for `token.actions.githubusercontent.com.` Select it to view its audience (sts.amazonaws.com) and provider details. The Terraform address `aws_iam_openid_connect_provider.github_actions ` is Terraform’s code reference; AWS shows the provider URL, not that Terraform label.

- This `sub` condition values list are the *allowlist*: they specify which GitHub repositories and branches may assume the AWS role.

  GitHub's immutable OIDC subject for the frontend repository includes its owner and repository IDs. The `github_owner_id` and `github_frontend_repository_id` variables must match the IDs in the repository's OIDC `sub` claim. AWS checks the token's `sub` against these entries; only matching repositories and branches can assume the role.

### Why this is important

This is a security best practice because:

- no long-lived AWS secret is stored in GitHub
- the role is assumed only from approved repos/branches
- the token is short-lived and automatically expires

### Permissions attached to the GitHub Actions role

The policy `aws_iam_policy.github_actions_ci_policy` in [github-actions-oidc.tf](./github-actions-oidc.tf) defines what an approved workflow can do after it assumes the role. The `aws_iam_role_policy_attachment.github_actions_ci_policy_attachment` resource attaches that policy to `aws_iam_role.github_actions_ci`; it does not create another role.

```hcl
resource "aws_iam_role_policy_attachment" "github_actions_ci_policy_attachment" {
  role       = aws_iam_role.github_actions_ci.name
  policy_arn = aws_iam_policy.github_actions_ci_policy.arn
}
```

The attached policy has three permission groups:

- **`ECRAuth` — `ecr:GetAuthorizationToken`:** lets the workflow log in to Amazon ECR. AWS requires `Resource = "*"` for this action.
- **`ECRPush` — ECR repository actions:** lets the workflow check image layers, upload layers, publish an image, and inspect repositories/images. The resource ARN limits these actions to ECR repositories in this AWS account (`arn:aws:ecr:*:${var.aws_account_id}:repository/*`).
- **`EKSRead` — `eks:DescribeCluster` and `eks:ListClusters`:** these permissions let a workflow look up EKS cluster details or list clusters. They are included in the role's policy, but the current frontend/backend build workflows do not use them; those workflows use the role to log in to ECR and push images. **So EKSRead is not needed for the current build-and-push flow.** It would only be needed if a workflow were later extended to query EKS (for example, to get cluster details before a deployment). These permissions do not themselves allow the workflow to deploy to Kubernetes.

**Example CI flow:** a push to an allowed repository branch starts a GitHub Actions workflow. The `configure-aws-credentials` step exchanges the GitHub OIDC token for temporary credentials for this role. The workflow then logs in to ECR, builds the application image, and pushes it to the repository. AWS checks the attached policy for each requested action; permissions outside these listed actions/resources are not granted by this policy.

---

## 8) Output values

The [outputs.tf](./outputs.tf) file exposes role ARNs:

```hcl
output "eso_role_arn" {
  description = "ARN of the External Secrets Operator IAM role"
  value       = aws_iam_role.eso_role.arn
}

output "argocd_role_arn" {
  description = "ARN of the ArgoCD IAM role"
  value       = aws_iam_role.argocd_role.arn
}

output "alb_controller_role_arn" {
  description = "ARN of the AWS Load Balancer Controller IAM role"
  value       = aws_iam_role.alb_controller_role.arn
}
```

This lets other automation or Helm values reference the exact role ARN.

---

## 9) Real-world example

Imagine the team wants to deploy new application code.

The workflow is:

1. GitHub Actions builds the Docker image
2. GitHub receives a temporary OIDC token
3. AWS validates it against the OIDC provider
4. GitHub Actions assumes the IAM role and pushes the image to ECR
5. Kubernetes uses IRSA roles to read the secret and manage AWS load balancing

This removes the need for static AWS keys and makes the process secure and auditable.

---

## 10) Summary

This module is the security and access layer for the platform.

It manages:

- OIDC trust for GitHub Actions
- EKS IRSA role trust policies
- Secrets Manager access for external-secrets
- ArgoCD access for GitOps automation
- AWS Load Balancer Controller access for traffic routing

In short: this is the identity foundation that makes the rest of the infrastructure secure.

---

## Key technical terms explained

### IAM role
An IAM role is a set of permissions that can be assumed by a trusted entity, such as a user, service account, or identity provider. Roles are safer than static credentials because they are temporary and scoped.

### Policy
A policy is a JSON document that defines what actions are allowed or denied. This repo uses AWS IAM policies to control who can access ECR, Secrets Manager, EKS, and other AWS services.

### Assume role
Assume role is the action of temporarily taking on an IAM role. This is what Kubernetes and GitHub Actions do through OIDC-based trust relationships.

### OIDC
OpenID Connect is a standard identity protocol. AWS can trust GitHub or an EKS OIDC provider so external workloads can authenticate without static keys.

### Federated identity
Federated identity means AWS trusts an external identity provider. In this project, GitHub and EKS both act as trusted identity providers.

### IRSA
IAM Roles for Service Accounts lets a Kubernetes service account assume an AWS role. This is used for External Secrets Operator, ArgoCD, and the AWS Load Balancer Controller.

### Service account
A Kubernetes service account is an identity assigned to application pods. It is often the thing mapped to an AWS role.

### AWS STS
AWS Security Token Service (STS) issues temporary credentials when a trusted entity assumes a role. This is how OIDC-based access works.

### Role ARN
An ARN is the unique AWS identifier for a role. It is used by systems that need to assume that role.

### Least privilege
Least privilege means granting only the minimum permissions needed for a role. The project follows this by scoping permissions to specific services and paths.

---

## Verify IAM in the AWS Console

Select the intended AWS account and region (`us-east-1` for this dev stack). IAM roles are account-level resources; use the environment/project names and trust-policy details to distinguish them.

```mermaid
flowchart LR
  GH[GitHub Actions OIDC] -->|approved repos and branches| CIROLE[GitHub Actions IAM role]
  CIROLE -->|ECR push and EKS describe policy| ECR[ECR]
  EKS[EKS OIDC provider] -->|service-account subject condition| ESO[External Secrets role]
  EKS --> ARGO[ArgoCD role]
  EKS --> ALB[AWS Load Balancer Controller role]
  ESO -->|GetSecretValue / DescribeSecret| SM[Secrets Manager pharma secrets]
```

| Terraform configuration | AWS Console location | What to verify |
|---|---|---|
| `github-actions-oidc.tf` OIDC provider | **IAM** → **Identity providers** → provider `token.actions.githubusercontent.com` | Provider URL is GitHub Actions and audience/client ID includes `sts.amazonaws.com`. |
| GitHub Actions trust policy | **IAM** → **Roles** → `pharma-dev-github-actions-role` → **Trust relationships** | Principal is the GitHub OIDC provider; audience is `sts.amazonaws.com`; subject conditions restrict access to the configured `zenpharma/frontend` and `zenpharma/backend` `main` and `develop` branches. |
| GitHub Actions permission policy | Role → **Permissions** | The attached policy grants the configured ECR image push/read actions and EKS describe/list access. Verify permissions are limited to what the pipeline needs. |
| EKS OIDC trust policies | **IAM** → **Roles** → `pharma-dev-eso-role`, `pharma-dev-argocd-role`, and `pharma-dev-alb-controller-role` → **Trust relationships** | Each role trusts the EKS OIDC provider and the expected Kubernetes namespace/service account subject (`external-secrets:external-secrets`, `argocd:argocd-application-controller`, or `kube-system:aws-load-balancer-controller`) with audience `sts.amazonaws.com`. |
| ESO Secrets Manager policy | `pharma-dev-eso-role` → **Permissions** → expand attached policy | Allowed actions include `secretsmanager:GetSecretValue` and `secretsmanager:DescribeSecret`, scoped to the configured `/pharma/*` secret path. |
| ALB controller permissions | `pharma-dev-alb-controller-role` → **Permissions** | The load balancer controller policy is attached and contains the EC2/Elastic Load Balancing actions defined in `modules/iam/main.tf`. Review the full policy and scope before changing it. |
| ArgoCD role | `pharma-dev-argocd-role` → **Trust relationships** and **Permissions** | This module creates the role and trust relationship. It does not attach an AWS permissions policy to the ArgoCD role in the inspected Terraform; do not assume it has AWS permissions unless another configuration attaches them. |
| Role tags and ARNs | Each role → **Tags** / role summary | Check project/environment tags and compare role ARNs against module outputs or Kubernetes/CI configuration. |

### Safe verification notes

- Inspect policy JSON and trust relationships; do not use **Switch role** or create long-lived access keys just to check configuration.
- A correct IAM role alone does not prove that a Kubernetes service account is annotated/configured to use it. Verify the corresponding Kubernetes service account configuration in the cluster as a separate step.
- IAM changes can grant broad access. Use Terraform plans and review policy diffs before applying changes.
