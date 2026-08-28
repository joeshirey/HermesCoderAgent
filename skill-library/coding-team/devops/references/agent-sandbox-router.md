# Agent Sandbox Router: Troubleshooting & Image Pull Guide

This reference guide documents a critical upstream packaging issue in the Kubernetes Special Interest Group (SIG) **`agent-sandbox`** project (specifically version `v0.4.6`) and details how to build and patch the sandbox router for GKE.

## The Bug: ImagePullBackOff on `sandbox-router`

When deploying the `agent-sandbox` extensions, pods utilizing the `sandbox-router` fail with an `ImagePullBackOff` error when referencing the public registry:

```
Failed to pull image "registry.k8s.io/agent-sandbox/sandbox-router:v0.4.6": 
rpc error: code = NotFound desc = failed to pull and unpack image "registry.k8s.io/agent-sandbox/sandbox-router:v0.4.6": 
not found
```

### Root Cause

1. In `kubernetes-sigs/agent-sandbox`, the core controller and standard runtime sandboxes are promoted to `registry.k8s.io` under the `agent-sandbox` namespace.
2. The `sandbox-router` (located at `clients/python/agentic-sandbox-client/sandbox-router/`) is **not** included in the upstream promotion list (`IMAGES_TO_PROMOTE` in `dev/tools/tag-promote-images`).
3. Therefore, the image `registry.k8s.io/agent-sandbox/sandbox-router:v0.4.6` **does not exist** on the public registry.
4. Upstream expects developers to build and push this image themselves, but downstream configurations (like `k8s/sandbox_router.yaml`) often contain hardcoded assumptions pointing to `registry.k8s.io`.

---

## The Solution: Manual Build & Registry Patch

To fix this, you must download the official `sandbox-router` source from the specific version release tag, submit a build to your Google Artifact Registry (GAR), and patch the deployment.

### Copy-Paste Shell Fix for GKE / Cloud Shell

Run this script inside your Cloud Shell / repository workspace:

```bash
# 1. Create a secure staging directory for the router
mkdir -p ~/sandbox-router-build && cd ~/sandbox-router-build

# 2. Download official v0.4.6 sandbox-router assets directly from GitHub
curl -sL https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/v0.4.6/clients/python/agentic-sandbox-client/sandbox-router/Dockerfile -o Dockerfile
curl -sL https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/v0.4.6/clients/python/agentic-sandbox-client/sandbox-router/requirements.txt -o requirements.txt
curl -sL https://raw.githubusercontent.com/kubernetes-sigs/agent-sandbox/v0.4.6/clients/python/agentic-sandbox-client/sandbox-router/sandbox_router.py -o sandbox_router.py

# 3. Source environment variables to resolve active registry parameters
cd ~/<project>
source ./setup-env.sh

# 4. Build and push the container to your project's Artifact Registry
gcloud builds submit --tag "${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${GOOGLE_CLOUD_PROJECT}/${ARTIFACT_REPO_NAME}/sandbox-router:v0.4.6" ~/sandbox-router-build

# 5. Patch k8s/sandbox_router.yaml to use your newly-built private image
sed -i "s|image: registry.k8s.io/agent-sandbox/sandbox-router:v0.4.6|image: ${ARTIFACT_REGISTRY_LOCATION}-docker.pkg.dev/${GOOGLE_CLOUD_PROJECT}/${ARTIFACT_REPO_NAME}/sandbox-router:v0.4.6|g" k8s/sandbox_router.yaml

# 6. Apply updated sandbox router configuration to the cluster
kubectl apply -f k8s/sandbox_router.yaml
```

This updates the pod's image spec, allowing GKE to seamlessly pull the container from the project's own Artifact Registry, transitioning the pod state to `Running`.
