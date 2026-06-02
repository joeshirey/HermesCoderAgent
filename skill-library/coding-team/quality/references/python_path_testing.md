# Python PYTHONPATH for Test Runners

When running Python test suites in modular backend projects (e.g., FastAPI, SQLAlchemy, Django apps where the source code resides in a subdirectory like `backend/app/` and tests are in `backend/tests/`), you may encounter import errors.

## The Problem

Running `uv run pytest` or standard `pytest` can fail with:

```
ImportError while loading conftest '/path/to/project/backend/tests/conftest.py'.
ModuleNotFoundError: No module named 'app'
```

This happens because the python virtual environment or runner does not automatically append the current directory (`backend/`) to `sys.path` when locating imports.

## The Workaround

Always prepend `PYTHONPATH=.` to the test command when running within the backend project directory:

```bash
# Correct execution pattern:
PYTHONPATH=. uv run pytest
```

This ensures that Python can correctly resolve relative imports (such as `from app.auth.dependencies import ...`) starting from the directory where the command is executed.
