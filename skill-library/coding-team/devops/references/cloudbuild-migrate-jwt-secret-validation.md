# Case Study: Pydantic Settings Validation Failures in Cloud Run Migration Jobs

## Problem & Symptoms

During Google Cloud Build pipeline runs, a decoupled Alembic migration step running as a one-shot Cloud Run Job fails during deployment (Step 5):

```
Step #5: Creating and running job... failed
Step #5: Job failed to deploy
Step #5: ERROR: (gcloud.run.jobs.deploy) The execution failed.
Step #5: Task migrate-job-b5s8r-task0 failed with exit code: 1 and message: The container exited with an error.
```

## Diagnostics (Container Stdout/Stderr Logs)

Querying the execution details using `gcloud logging read` exposes the root cause:

```
Container called exit(1).
Value error, JWT_SECRET_KEY must be changed from its default value in production. Set a strong, random secret via the JWT_SECRET_KEY environment variable. [type=value_error, input_value={}, input_type=dict]
Traceback (most recent call last):
  ...
  File "/app/alembic/env.py", line 24, in <module>
    from app.config import settings
  File "/app/app/config.py", line 110, in <module>
    settings = Settings()
  File "/usr/local/lib/python3.12/site-packages/pydantic/main.py", line 263, in __init__
    validated_self = self.__pydantic_validator__.validate_python(data, self_instance=self)
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
```

## Root Cause

When the container boots to run `alembic upgrade head` inside a serverless GCP environment, Alembic imports the application configuration:
`from app.config import settings`

Since the active database is PostgreSQL (production), the `Settings` class executes its production-grade model validator, checking that `JWT_SECRET_KEY` is not its local-development default value. Because the Cloud Run Job's deployment parameters only bound the database password and did *not* bind the `JWT_SECRET_KEY` secret, Pydantic's initialization threw a validation error and exited, failing the entire job execution before any SQL commands could be compiled.

## Resolution

Symmetrically map all required production secrets inside the `gcloud run jobs deploy` CLI command in your `cloudbuild.yaml` file so they are available to the container's environment context at runtime:

```yaml
  # Deploy and run migrations as a Cloud Run job
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: 'bash'
    args:
      - '-c'
      - |
        gcloud run jobs deploy migrate-job \
          --image=us-central1-docker.pkg.dev/$PROJECT_ID/fantasy-golf/backend:$SHORT_SHA \
          --command="alembic" \
          --args="upgrade","head" \
          --region=${_REGION} \
          --set-cloudsql-instances=your-gcp-project-id:us-central1:fantasy-golf-db \
          --set-secrets=DB_PASSWORD=db-password:latest,JWT_SECRET_KEY=jwt-secret-key:latest \
          --set-env-vars=DB_SOCKET_DIR=/cloudsql/your-gcp-project-id:us-central1:fantasy-golf-db,DB_USER=fantasygolf,DB_NAME=fantasygolf \
          --execute-now \
          --wait
```
