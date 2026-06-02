# GKE Autopilot & Gateway Ingress Troubleshooting Guide

This guide documents critical execution and routing behaviors when deploying containerized applications to Google Kubernetes Engine (GKE) Autopilot clusters with GKE Gateway API in production.

---

## 1. GKE Autopilot CPU-to-Memory Resource Constraints

GKE Autopilot enforces strict resource ratios to optimize node utilization. If an application's pod specification violates these constraints, GKE will automatically mutate (override) the resource requests or refuse to schedule the pod.

### Ratio Rules

* For standard workloads, the ratio of CPU to Memory must fall between **1 vCPU : 1 GiB** and **1 vCPU : 6.5 GiB**.
* For example, requesting `500m` (0.5 vCPU) with `256Mi` memory represents a ratio of **1 vCPU : 512 MiB**, which is below the Autopilot minimum.

### The Impact

* GKE Autopilot will silently mutate the Pod spec on scheduling to raise the memory request to `512Mi` to satisfy the 1 vCPU : 1 GiB minimum.
* This discrepancy can lead to confusing state mismatches during `kubectl describe` or local Helm chart validation.

### Best Practice

Explicitly declare compliant resources in the pod specification to avoid automated GKE mutations:

```yaml
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi" # Prevents silent GKE Autopilot overrides
          limits:
            cpu: "500m"
            memory: "512Mi"
```

---

## 2. Gateway Health Check Bootstrapping & Workload Identity Delays

When using the modern GKE Gateway API (`gatewayClassName: gke-l7-global-external-managed`) to set up a global application load balancer, backend health checks can fail on startup due to timing race conditions.

### The Race Condition

1. **Load Balancer Provisioning:** GKE Gateway routes traffic to a backend service based on an external GKE `HealthCheckPolicy`.
2. **Workload Identity Propagation:** On startup, the GKE Metadata Server takes up to **60 seconds** to fully populate short-lived Google Cloud IAM credentials (Workload Identity Federation) into a newly scheduled pod.
3. **Database Dependency Failure:** If the load balancer's HTTP health check path is tied to an endpoint that queries a database (e.g., BigQuery, Cloud SQL) on startup, the query will fail with HTTP 500 because the database client is unauthorized during that first 60 seconds.
4. **Ingress Lockout:** GKE marks the pod as `Unhealthy` and blocks external traffic, causing the entire global ingress gateway to stay down with HTTP 502/404 errors.

### The Solution: Database-Independent Health Checks

Always expose a lightweight, database-independent HTTP `/healthz` or `/health` path in the web service, separate from business logic endpoints:

#### 1. In the Web Server (Go/FastAPI)

Register a lightweight, immediate health route:

```go
// In Gin
r.GET("/healthz", func(c *gin.Context) {
    c.JSON(http.StatusOK, gin.H{"status": "healthy"})
})
```

#### 2. In GKE HealthCheckPolicy

Target the database-independent `/healthz` path instead of a data-fetching endpoint:

```yaml
apiVersion: networking.gke.io/v1
kind: HealthCheckPolicy
metadata:
  name: backend-health-check
  namespace: hackathon-judge
spec:
  default:
    config:
      type: HTTP
      httpHealthCheck:
        requestPath: /healthz # database-independent
  targetRef:
    group: ""
    kind: Service
    name: backend
```

---

## 3. Load Balancer Provisioning Latency (The 5-Minute Rule)

Global managed application load balancers in GCP are not instantaneous.

* **The Symptom:** Immediately after running `kubectl apply -f k8s/`, accessing the Gateway IP will yield `HTTP 404` or `HTTP 502`.
* **The Cause:** Google Cloud takes **5 to 7 minutes** to configure global Anycast IP addresses, propagate global URL maps, and complete the initial green health checks.
* **Action:** Educate users/teams to wait 5-7 minutes before concluding that routing or ingress configurations are broken.
