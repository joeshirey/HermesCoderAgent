# PostgreSQL Parity Testing and Local Credential Handling

When migrating automated test suites from SQLite to PostgreSQL (to ensure full production-database parity), you must handle strict referential integrity rules and keep local database credentials out of command lines.

---

## 1. PostgreSQL Referential Integrity Rigor (Foreign Keys)

By default, in-memory SQLite connections in tests do not enforce Foreign Key (FK) constraints unless explicitly enabled via SQLite connections hooks (e.g. `PRAGMA foreign_keys=ON`). This often hides dangling references in unit tests.

PostgreSQL, however, strictly enforces referential integrity natively.

### The Problem

Tests designed on SQLite often seed nested models (such as `Invitation` or `RefreshToken`) by passing mock, nonexistent parent IDs directly:

```python
invitation = Invitation(
    email="newplayer@example.com",
    invited_by="some-fake-admin-id",  # Fails on PostgreSQL!
)
```

While SQLite lets this slide, PostgreSQL throws `ForeignKeyViolationError` (FastAPI integrity error `409 Conflict`), crashing the test setup.

### The Solution

Always explicitly query or seed the valid parent records (`User`, `Season`, etc.) first in your test setups, and thread their real, persisted primary keys into any dependent child records:

```python
# Seed the valid parent first
admin = User(id="real-admin-id", email="admin@example.com", is_admin=True)
db_session.add(admin)
await db_session.commit()

# Reference the real parent key
invitation = Invitation(
    email="newplayer@example.com",
    invited_by=admin.id,  # Safe and compatible on all dialects!
)
```

---

## 2. SQLAlchemy Async Driver Enforcement

When dynamically parametrizing your test database URL from the environment in `conftest.py`, ensure that the default fallback retains its async driver suffix:

* **Wrong:** `sqlite://` (Defaults to the synchronous `pysqlite` driver, which causes SQLAlchemy `AsyncEngine` to raise `InvalidRequestError: The asyncio extension requires an async driver`).
* **Right:** `sqlite+aiosqlite://` (Specifies the correct async SQLite driver).

```python
# Read from env, safely defaulting to the async SQLite driver
_RAW_DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite://")
_TEST_DATABASE_URL = _build_url(_RAW_DATABASE_URL)
```

---

## 3. Handling Local Database Credentials

Agent harnesses may redact credential-like strings in command output and inputs. Do not try to work around redaction; instead, keep credentials out of command lines entirely.

* **Load credentials from the environment.** Read `DATABASE_URL` (and any password) via `os.environ`, and supply it from your shell environment or a git-ignored `.env` file loaded by your test runner or `python-dotenv`.
* **Never inline credentials** in commands, scripts, docs, or tracked files, in plain text or in any encoded form.
* **Use throwaway local-only passwords** for disposable dev/test containers, and never reuse real credentials there.

```bash
# .env (git-ignored)
# DATABASE_URL=postgresql+asyncpg://postgres:<local-dev-password>@localhost:5432/app_test

set -a; source .env; set +a
pytest
```

---

## 4. High-Performance Test Isolation & Database Concurrency (GHA CI Optimization)

When transitioning an async pytest suite to run against a real PostgreSQL container (especially in GHA), having a global `autouse=True` database setup/teardown fixture causes massive performance bottlenecks (such as GHA runs taking 9+ minutes) and connection concurrency conflicts (`sqlalchemy.exc.InterfaceError: cannot perform operation: another operation is in progress`).

### The Problem
If a database setup/cleanup fixture (such as one executing `TRUNCATE CASCADE` on Postgres) has `autouse=True`, `pytest-asyncio` will execute it for **every single test case** in the entire suite—including purely synchronous, stateless unit tests (like math/standings utilities or data encoders) that do not use any database at all. This results in:
* Connection/resource pool exhaustion from rapid connection cycling.
* Overlap errors where one test's teardown overlaps with another's setup in the async event loop.

### The Solution
Decouple the database setup fixture by removing `autouse=True`, and make only the database-touching fixtures (like `db_session` and HTTP `client` overrides) explicitly depend on it:

```python
# conftest.py
@pytest_asyncio.fixture
async def setup_db():
    # Only run DB setup/cleanup when explicitly required
    yield
    async with engine_test.begin() as conn:
        await conn.execute(sa.text("TRUNCATE TABLE ... RESTART IDENTITY CASCADE;"))

@pytest_asyncio.fixture
async def db_session(setup_db) -> AsyncGenerator[AsyncSession, None]:
    async with async_session_test() as session:
        yield session

@pytest_asyncio.fixture
async def client(setup_db) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()
    # ... setup overrides ...
    yield client
```

This ensures that:
* Pure unit tests bypass all database setups/teardowns completely, running instantly with zero connection overhead.
* Integration tests that request `db_session` or `client` automatically and safely trigger the cleanup.
* Executions are robust, concurrency-safe, and up to **17x faster**!
