# Python UV Environments & Pydantic Settings Leaks

In Python codebases managed with modern packagers like `uv` (where dependencies are isolated in subdirectories, e.g. `backend/uv.lock` and `backend/.venv`), running tests via the default or global virtualenv can lead to dependency mismatches and configuration validation errors.

---

## 1. Virtual Environment Divergence

### The Symptom
Running `pytest` directly in the project root can default to the active agent or system `pytest` binary (e.g., `~/.hermes/hermes-agent/venv/bin/pytest`). This results in:
```
ModuleNotFoundError: No module named 'authlib'
```
Even if `uv` is installed, running `uv run pytest` in the wrong working directory can fail to locate the local lockfile or local virtualenv.

### The Fix
Always navigate to the subdirectory containing the package/lockfile (e.g. `backend/`) and run tests using:
```bash
uv run pytest
```
This forces `uv` to resolve and use the local `.venv` environment and its specific installed dependencies.

---

## 2. Pydantic Settings Extra Environment Leakage

### The Symptom
Developer workstations or parent agent processes often define environment variables (e.g., `POSTGRES_PASSWORD`, `GEMINI_API_KEY`) for global services. When Pydantic Settings parses the system environment, these matching variables are mapped to configuration settings.

If the application settings class (inheriting from `BaseSettings`) does not define these specific fields, and is configured to forbid extra inputs, pytest fails immediately with a `ValidationError`:
```
E   pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings
E   postgres_password
E     Extra inputs are not permitted [type=extra_forbidden, input_value='postgres', input_type=str]
E   gemini_api_key
E     Extra inputs are not permitted [type=extra_forbidden, input_value='AIzaSy...', input_type=str]
```

### The Fix (Durable Configuration)
To prevent unexpected environment variables from crashing the test runner or application boot, explicitly configure the Pydantic Settings model to **ignore extra inputs** in its `model_config`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App configuration fields...
    
    # Allow extra environment variables without validation failure
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore"  # Crucial for local & agent test run isolation
    }
```

### The Fix (Environment Isolation)
Alternatively, if configuration edits are restricted, run the test runner with filtered environment variables using `env -u` or by clearing the env:
```bash
env -u POSTGRES_PASSWORD -u GEMINI_API_KEY uv run pytest
```
