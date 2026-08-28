---
name: devops
description: "CI/CD, deployment, infrastructure, and environment configuration."
version: 1.0.0
author: Hermes Coder (adapted from Squad network/inco)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [cicd, deployment, infrastructure, docker, github-actions]
    related_skills: [architect, security, implementer]
---

# DevOps Role

Apply this lens when evaluating CI/CD changes, deployment configurations, or infrastructure concerns.

## Charter

**Identity:** DevOps engineer responsible for build, deploy, and infrastructure reliability.

**Expertise:**

- CI/CD pipeline design (GitHub Actions, etc.)
- Container configuration (Docker, docker-compose)
- Environment management and configuration
- Build tooling and dependency management
- Monitoring and observability setup

**Responsibilities:**

- Review CI/CD pipeline changes for correctness
- Ensure deployment configurations are production-ready
- Verify environment variables and secrets are properly managed
- Check that build processes are reproducible
- Flag infrastructure changes that need careful rollout

## DevOps Review Checklist

- [ ] CI/CD pipelines run all necessary checks (lint, test, build)
- [ ] Docker/container configs are optimized (multi-stage builds, minimal images)
- [ ] Environment variables documented and not hardcoded
- [ ] Build is reproducible (pinned dependencies, lockfiles)
- [ ] Deployment has rollback capability
- [ ] Health checks and readiness probes configured
- [ ] Secrets managed via proper secret management (not env files in repo)

## Dispatch Template

When dispatching DevOps tasks (see active harness skill for exact command syntax):

- **Prompt:** "Review and update the CI/CD configuration in `<files>`. Ensure: builds are reproducible, tests run in CI, secrets are properly managed."
- **Scope:** read, edit, write, run commands
- **Timeout:** 180s

## Automated Tasks & Notifications

When designing or updating automated cron jobs, background runners, or daily scripts/notifications:

- **Enforce One-Liner Success Outputs:** Keep successful runs extremely brief and clean. Do not output verbose command logs (e.g., raw Git commit/push stdout, build details) on successful operations. Redirect stdout/stderr of intermediate subcommands to `/dev/null` and output a single, high-level status line (e.g., `Backup completed successfully at TIMESTAMP`).
- **Handle No-Ops Gracefully:** If an automated job runs but determines that no action is required (e.g., no file changes found), output a single concise line (e.g., `No changes detected. Backup skipped.`) to avoid spamming the user with long empty logs or unnecessary text.
- **Fail Verbosely:** On actual failures, let errors surface and output diagnostic details so the issue can be actively debugged.

## Advanced CI/CD & Container Hardening Patterns

### 1. Minimal-Image Container Healthchecks (Slim/Alpine Images)

When hardening containers in multi-service configurations, healthchecks provide essential orchestration signals (enabling correct startup order). However, minimal base images (such as `python:slim` or `alpine`) often exclude `curl` or `wget`.

- **Python-Slim Images:** Avoid adding unnecessary packages. Execute a standard library Python one-liner to perform HTTP checks:
    `test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]`
- **Nginx/Alpine Images:** Use the native busybox `wget` for quick HTML root verification:
    `test: ["CMD-SHELL", "wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1"]`
- **Dependency Gating:** Configure the reverse proxy/frontend port mapping to bind only to loopback (`127.0.0.1:<port>`) in development, and use `depends_on` to gate frontend boot on the API being healthy:

    ```yaml
    depends_on:
      backend:
        condition: service_healthy
    ```

### 2. Lint and Build Hygiene for Green CI Pipelines

When introducing automated CI/CD checks (such as GitHub Actions) to existing legacy codebases, strict linter checks often fail on non-breaking files (e.g., pedantic style choices or unused imports).

- **ESLint/TS Downgrades:** Rather than rewriting complex state management or component code under pressure, adjust `eslint.config.js` to treat styling, refresh, or context rules as `'warn'` instead of `'error'`. This allows build checking (`npm run build` targeting `tsc -b && vite build`) to act as the primary compile gate.
- **Ruff Linter Suppressions:** When running Ruff checks on Python, include `--ignore E402` in the CI CLI invocation if standard files perform inline warnings/warnings suppressions before module imports. This prevents required order-suppressions from failing the pipeline.
- **Ruff Monorepo/Subdirectory Working Directory:** If ruff is installed in a subdirectory virtual environment (e.g., `backend/.venv` via `uv sync --directory backend`), executing `uv run ruff check` at the repository root in CI will fail to find `ruff` with a "No such file or directory (os error 2)" error. Always configure the linter step to run with the correct `working-directory: <sub-folder>` (or specify `--directory <sub-folder>` in uv) to ensure it executes within the correct virtual environment context.
- **NPM Registry Conflicts:** If package installation fails with E401 authentication errors on standard public packages, inspect `package-lock.json` for resolved URLs pointing to private Artifact Registries (e.g., `us-npm.pkg.dev` or Artifactory). Symmetrically replace private URLs with public npm registry equivalents (`https://registry.npmjs.org`) in the lockfile to unlock public builds.

## Common Pitfalls & Troubleshooting

- **Serverless Scaling & State Loss (GCP Cloud Run / AWS Fargate):** Schedulers based on in-memory timers (such as Python's `APScheduler` or Node's `node-cron` running inside the app process) will fail or duplicate tasks in serverless environments. Containers scale down to zero when idle, completely wiping out memory-scheduled triggers. Conversely, scaling up to multiple concurrent instances will execute duplicate jobs.
  - *Solution:* Decouple scheduling from the application container. Expose a secure HTTP endpoint (e.g., `/api/notifications/trigger-deadline` gated by a secure pre-shared token header) and configure an external distributed cloud cron scheduler (such as **Google Cloud Scheduler** or **AWS EventBridge**) to trigger it.
- **Upstream Container Packaging Bugs (Agent-Sandbox):** Upstream projects sometimes fail to promote minor helper utility containers to public repositories (such as `registry.k8s.io`), causing silent `ImagePullBackOff` failures.
  - For GKE-based `agent-sandbox` issues where the `sandbox-router` fails to pull, refer to:
    `[references/agent-sandbox-router.md](references/agent-sandbox-router.md)`
- **GKE Autopilot & Gateway Ingress Troubleshooting:** Working with Autopilot constraints, global Gateway health check bootstrap failures, and Load Balancer warmups:
  - Refer to `[references/gke-autopilot-gateway-troubleshooting.md](references/gke-autopilot-gateway-troubleshooting.md)`

### 3. Serverless Deploy-Time Smoke Testing (Cloud Build / Docker-in-Docker)

When introducing pre-deployment container smoke tests in modern CI/CD pipelines (such as Google Cloud Build or equivalent Docker-in-Docker environments), we must navigate container network namespaces and filesystem write privileges:

- **Cloud Build Shared Networking (The Localhost Pitfall):** Cloud Build steps execute inside isolated container runtimes running on a shared Docker network named `cloudbuild`. Background containers launched with `docker run -d` within a step are running as sibling containers on the same host. They **cannot** be accessed via `localhost` from other steps or within the same step. To enable communication, you must attach your background containers to the shared network using `--network cloudbuild` and address them directly by their container name (e.g. `http://test-backend:8000/api/health` and `http://test-frontend:8080/`).
- **Unprivileged USER Write Permissions (The SQLite Crash):** Hardened, production-ready Docker images often run under an unprivileged user (such as `USER appuser`) for security compliance. If a smoke-test container boots up and attempts to create or write an in-memory or file-based SQLite database in the default application directory (e.g. `./smoke_test.db` in `/app`, which was populated by root during build), it will crash with `sqlite3.OperationalError: unable to open database file`. Point `DATABASE_URL` inside the smoke-test environment to a globally writable directory like `/tmp/smoke_test.db` (e.g. `sqlite:////tmp/smoke_test.db`) to ensure successful, permission-safe execution.

### 4. Decoupled One-Shot Database Migrations (Cloud Run Jobs / Cloud Build)

Running database migrations (such as `alembic upgrade head`) directly inside your application container's startup command (`CMD` or entrypoint) is a dangerous production anti-pattern. On Cloud Run (or any serverless platform), scale-ups, cold starts, and multi-instance scaling events will launch multiple concurrent containers, causing migration races, table locking, or database connection pool exhaustion.

- **Uvicorn-Only Startup:** Remove all migration commands from the container's startup command, configuring it strictly to execute the web server (e.g., `uvicorn app.main:app`).
- **Deploy-Time Cloud Run Jobs:** Configure a dedicated Google Cloud Build step that deploys and executes a one-shot Cloud Run Job (e.g., `gcloud run jobs deploy migrate-job --execute-now --wait`) *before* the application's service replacement step. This ensures that:
  - Database upgrades run sequentially and isolated from active traffic.
  - Successful database migration is a **hard gate**—the build blocks and fails immediately if migrations fail, protecting your production environment from running new application code against a stale database schema.
  - The migration job is run against the newly built image tag (e.g., `:$SHORT_SHA`), guaranteeing that migration definitions perfectly match the application revision.
  - **Symmetric Secret Bindings for App Configurations (The Pydantic Startup Crash):** If your application settings (such as Pydantic Settings) run strict validation guards on startup (such as checking that production secrets like `JWT_SECRET_KEY` are changed from their default values when running against a production database dialect), executing Alembic commands inside the container will trigger those validation checks. If those secrets are missing from the job context, the container will immediately exit with a `ValidationError` / `exit(1)` before migrations even start. Always bind all necessary production secrets symmetrically (`--set-secrets=...`) to the migration job's environment context.
  - *Case Study Reference:* For a complete diagnostic and resolution breakdown of this exact Pydantic ValidationError crash under Cloud Run Job migrations, see: `[references/cloudbuild-migrate-jwt-secret-validation.md](references/cloudbuild-migrate-jwt-secret-validation.md)`.

### 5. Least-Privilege Container Database Routing

Avoid using database superuser credentials (such as the default `postgres` role) inside container environment connections.

- **Dynamic Connection String Construction:** Refactor your container's startup command and configurations to dynamically assemble the `DATABASE_URL` from separate environmental inputs: `postgresql://${DB_USER:-postgres}:${DB_PASSWORD} @ /${DB_NAME:-app_db}?host=${DB_SOCKET_DIR}`. This maintains seamless local/development backward-compatibility (falling back safely to standard defaults) while unlocking custom database credentials in production.
- **Service Configuration Segregation:** Supply explicit, unprivileged `DB_USER` and `DB_NAME` values (such as `app_db`) in your service specification YAML files, restricting connection privileges purely to the schema operations required by the runtime application.

### 6. Fork Isolation for Deployments & Registry Publications (OIDC / Secrets Guard)

In open-source or shared repositories with active personal forks, release, deployment, or package-publishing workflows (such as publishing to NuGet, npm, or PyPI) will frequently execute on forks (e.g. on branches pushed to the fork's development branch). Because forks do not inherit OIDC trusted publishing configurations, repository variables, or secrets, these workflows will crash and create false-alarm failure alerts on the fork.

- **Upstream Repository Guarding:** Always add an explicit repository-gated `if` constraint to the publish or deploy job definition in GitHub Actions:
  ```yaml
  jobs:
    publish:
      if: github.repository == 'bradygaster/squad' # Replace with canonical upstream owner/repo
      runs-on: ubuntu-latest
  ```
- **Silent Skip:** This allows the pipeline to bypass the publishing or deployment steps gracefully when running under a fork's namespace, keeping the forks' actions tab clean of unnecessary false failures.

### 7. Dynamic Secret Manager Version Pinning (Resolve-at-Deploy)

To prevent runtime environment drifts and secure immutable rollbacks, avoid referencing the floating `latest` alias for Secret Manager secrets in production manifests. Instead, resolve and stamp concrete integer versions at deploy time:

- **Service Manifests (Knative / Kubernetes):** Keep the committed source YAML as `key: latest` to maintain manual deployability. Add a CI step (e.g. Google Cloud Build using `gcloud`) that dynamically fetches the latest enabled integer version of each runtime secret:
  ```bash
  DB_PASSWORD_VER=$(gcloud secrets versions list db-password --filter='state:enabled' --sort-by=~createTime --limit=1 --format='value(name)')
  ```
  Then, use a robust Python regex one-liner to perform a targeted in-place edit in the manifest file before deployment without corrupting comments or YAML structure:
  ```bash
  python3 -c 'import sys, re; args = {sys.argv[i].lstrip("-").replace("-", "_"): sys.argv[i+1] for i in range(1, len(sys.argv), 2) if i+1 < len(sys.argv)}; content = open("infra/backend-service.yaml").read(); pin = lambda text, name, ver: re.sub(rf"(key:\s*)latest(\s*\n\s*name:\s*{name}\b)", rf"\g<1>{ver}\g<2>", text); [content := pin(content, name.replace("_", "-"), ver) for name, ver in args.items()]; open("infra/backend-service.yaml", "w").write(content)' --db-password "$DB_PASSWORD_VER" --jwt-secret-key "$JWT_SECRET_KEY_VER"
  ```
- **One-Shot Jobs (Database Migrations):** Symmetrically resolve active versions inside the execution step and pass them directly as a pinned parameter string (e.g., `--set-secrets=DB_PASSWORD=db-password:$$DB_PASSWORD_VER`).
- **Build-Time Limitations:** Note that secrets injected at build-time (e.g., `availableSecrets` in Cloud Build to populate frontend environment variables during compilation) are resolved at build-trigger initialization—before any build steps run. These are out of scope for deploy-time step pinning and can be left as `latest` with a clarifying documentation comment.
