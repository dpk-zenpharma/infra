# Script execution order

The numbered scripts are setup and deployment stages. Run them after Terraform
has provisioned the AWS infrastructure and EKS cluster. The full recommended
sequence is:

```text
Terraform infrastructure
        |
        v
01_install_prerequisites.py
        |
        +--------------------+
        v                    v
02_bootstrap_argocd.py   03_setup_external_secrets.py
        |                    |
        +----------+---------+
                   v
          04_run_pipeline.py
                   |
                   v
         05_deploy_services.py
                   |
                   v
         06_verify_deployment.py
```

Scripts 02 and 03 both require the platform components installed by script 01.
They configure separate parts of the cluster and can technically be run in
either order. Script 04 builds and pushes container images; script 05 requires
the Argo CD setup, the secret resources, and those images to be ready. Script 06
checks the deployment created by script 05.

The recommended sequence runs 02 and 03 before 04, although the build workflow
does not itself depend on Argo CD or ESO being configured. Do not run script 05
until all three prerequisites (02, 03, and 04) have completed successfully.

| Stage | Script | Main purpose | Requires |
|---|---|---|---|
| 1 | [01_install_prerequisites.py](./01_install_prerequisites.py) | Installs AWS Load Balancer Controller, Argo CD, and External Secrets Operator into EKS. | Terraform-created EKS cluster and IAM resources; `kubectl`, `helm`, AWS CLI. |
| 2 | [02_bootstrap_argocd.py](./02_bootstrap_argocd.py) | Registers the GitOps repository in Argo CD and creates the `pharma` AppProject. | Script 01; `kubectl`; GitOps repository URL and read-access credentials; local GitOps files are optional. |
| 3 | [03_setup_external_secrets.py](./03_setup_external_secrets.py) | Connects ESO to AWS Secrets Manager with IRSA and creates environment-specific secret sync resources. | Script 01; Terraform-created ESO IAM role/OIDC trust; Secrets Manager entries; `kubectl`. |
| 4 | [04_run_pipeline.py](./04_run_pipeline.py) | Triggers selected GitHub Actions workflows to build and push images and update GitOps image tags. | GitHub CLI authenticated with access to the source repositories and their workflows. |
| 5 | [05_deploy_services.py](./05_deploy_services.py) | Applies selected Argo CD Application manifests and waits for sync/health. | Scripts 02, 03, and 04; local GitOps application manifests; `kubectl`. |
| 6 | [06_verify_deployment.py](./06_verify_deployment.py) | Checks pods, Argo CD applications, external secrets, services/Ingress, and selected HTTP endpoints. | Script 05 should have applied the apps; `kubectl`; a reachable cluster and provisioned ALB for HTTP checks. |

## Running the scripts

Run commands from the `infra` repository root in an environment that has
Python 3 and the tools required by the specific script. Example:

```bash
python3 scripts/01_install_prerequisites.py
python3 scripts/02_bootstrap_argocd.py
python3 scripts/03_setup_external_secrets.py
python3 scripts/04_run_pipeline.py
python3 scripts/05_deploy_services.py
python3 scripts/06_verify_deployment.py
```

Scripts 01, 02, and 05 resolve the default GitOps path relative to the script
location, but can also accept `GITOPS_PATH`. Scripts 03 and 06 target the
currently configured Kubernetes context; script 04 operates on GitHub Actions.
For scripts that change cluster state, confirm that `kubectl` is pointed at the
intended EKS cluster and that the selected environment is correct.

Each script has a detailed guide:

- [01 installer guide](./01_install_prerequisites.md)
- [02 Argo CD bootstrap guide](./02_bootstrap_argocd.md)
- [03 External Secrets setup guide](./03_setup_external_secrets.md)
- [04 CI pipeline guide](./04_run_pipeline.md)
- [05 service deployment guide](./05_deploy_services.md)
- [06 verification guide](./06_verify_deployment.md)
