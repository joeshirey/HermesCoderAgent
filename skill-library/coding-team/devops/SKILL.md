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

## Common Pitfalls & Troubleshooting

- **Upstream Container Packaging Bugs (Agent-Sandbox):** Upstream projects sometimes fail to promote minor helper utility containers to public repositories (such as `registry.k8s.io`), causing silent `ImagePullBackOff` failures.
  - For GKE-based `agent-sandbox` issues where the `sandbox-router` fails to pull, refer to:
    `[references/agent-sandbox-router.md](references/agent-sandbox-router.md)`
- **GKE Autopilot & Gateway Ingress Troubleshooting:** Working with Autopilot constraints, global Gateway health check bootstrap failures, and Load Balancer warmups:
  - Refer to `[references/gke-autopilot-gateway-troubleshooting.md](references/gke-autopilot-gateway-troubleshooting.md)`
