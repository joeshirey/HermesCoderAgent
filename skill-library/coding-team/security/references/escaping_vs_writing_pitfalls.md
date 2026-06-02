# Over-Sanitization and Shell Escaping Pitfalls

When designing secure boundaries in systems that execute commands or write files (such as automated sandboxes, code agents, or remote executors), developers frequently mistake the **execution context** for the **storage context**, leading to over-sanitization and corruption.

## 1. The Shell Escaping vs. File Writing Pitfall (The `shlex` Trap)

### The Bug

A classic implementation pattern where a secure shell string generator is incorrectly used to sanitize strings written to plain text or markdown files on disk:

```python
# SECURE (for shell context): prevents command injection in command string execution
safe_url = shlex.quote(github_url)
sandbox.commands.run(f"git clone {safe_url} repo")

# BROKEN (for file context): corrupts the file contents
safe_prompt = shlex.quote(SANDBOX_PROMPT)
sandbox.files.write('prompt.md', safe_prompt)
```

### Why It Fails

`shlex.quote()` is specifically designed to shell-escape strings so they are safe when evaluated by shell interpreters (e.g. bash).

* It wraps the string in outer single quotes (`'`) and escapes inner quotes.
* If written to a file directly, the file contents on disk literally start and end with `'` and all inner quotes are corrupted (e.g., `\'` or nested quote formatting).
* When downstream processors (such as sandboxed LLMs or parsers) read `prompt.md`, they receive a corrupted string, which causes silent failures, corrupted outputs, or parser syntax errors.

### The Standard Rule

Keep the contexts strictly decoupled:

1. **Command Line Arguments (Shell Context):** Use `shlex.quote()` (or parameterized subprocess calls) strictly when interpolating untrusted variables directly into shell scripts or raw CLI strings.
2. **File System Writing (Disk Context):** Write the **raw** string directly using standard file writers (e.g. `.write()`). File system APIs do not execute strings; they write bytes. No shell parser is invoked during a file-write, so no command injection is possible here.

---

## 2. Sandboxing & Input Boundary Checklist

| Operation | Context | Sanitization Required | Tool / Pattern |
| :--- | :--- | :---: | :--- |
| **Executing a local shell command** | Shell Interpreter | **Yes** | `shlex.quote(var)` (Python) or parameterized commands (Go/Node) |
| **Writing a file to disk** | File system (FS) | **No (Literal content)** | Write raw content directly (avoid `shlex` or shell-escaping) |
| **Ensuring path safety** | Path traversal | **Yes** | Validate that the target path resolves within the allowed workspace directory |
| **Passing prompts to LLM APIs** | API payload | **No (Structured)** | Construct structured JSON arrays of blocks; do not escape payload contents as shell strings |
