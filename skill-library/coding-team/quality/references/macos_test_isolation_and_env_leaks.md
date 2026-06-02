# macOS Test Isolation & Global Environment Leaks

A common cause of divergent test behaviour between Linux-based CI environments and local macOS development machines is the handling of platform-specific global path resolution.

This reference details the "macOS configuration leak" pitfall, its diagnostic symptoms, and a robust pattern for clean test isolation.

---

## The Pitfall: Traditional Platform Branching

When writing applications or CLI tools that store state, caching, or configurations globally, developers frequently use platform-specific defaults:

```typescript
// PITFALL: Traditional platform-specific resolution
export function resolveGlobalPath(): string {
  const platform = process.platform;
  
  if (platform === 'win32') {
    return process.env['APPDATA'] ?? ...;
  } else if (platform === 'darwin') {
    return path.join(os.homedir(), 'Library', 'Application Support', 'myapp');
  } else {
    // Linux / other POSIX respects XDG
    return process.env['XDG_CONFIG_HOME'] ?? path.join(os.homedir(), '.config', 'myapp');
  }
}
```

### Why This Fails in Test Suites on macOS

1. **Test Isolation Bypass:** Standard E2E/integration test suites isolate filesystem operations by setting `XDG_CONFIG_HOME` (e.g., to a temporary test-specific sandbox path).
2. **The Leak:** On Linux-based CI systems, the code above correctly resolves `XDG_CONFIG_HOME` and writes to the sandbox. But on macOS development machines, `process.platform === 'darwin'` triggers the macOS branch, completely ignoring the `XDG_CONFIG_HOME` test override.
3. **Severe Consequences:**
   - The test runner reads from and mutates the developer's **real, active system configuration** under `~/Library/Application Support/`, potentially damaging user state.
   - Tests that expect a pristine, empty database/configuration file will find existing developer configurations, causing bizarre, non-deterministic local test failures that never manifest in CI.

---

## The Safe Resolution Pattern

To prevent platform-specific leaks and guarantee perfect macOS local test isolation, always check and respect standard Unix-like test overrides (such as `XDG_CONFIG_HOME`) **first** across all platforms before falling back to native OS paths:

```typescript
export function resolveGlobalPath(): string {
  const platform = process.platform;
  let base: string;

  // 1. High-priority Unix override (enables perfect macOS/Linux test isolation)
  const xdgOverride = process.env['XDG_CONFIG_HOME'];

  if (xdgOverride) {
    base = xdgOverride;
  } else if (platform === 'win32') {
    base = process.env['APPDATA']
      ?? process.env['LOCALAPPDATA']
      ?? path.join(os.homedir(), 'AppData', 'Roaming');
  } else if (platform === 'darwin') {
    base = path.join(os.homedir(), 'Library', 'Application Support');
  } else {
    base = path.join(os.homedir(), '.config');
  }

  // 2. Append the app directory suffix
  // Note: if XDG_CONFIG_HOME is explicitly targeted to /path/to/test-sandbox, 
  // we append the app name to maintain standard sub-folder structure
  return path.join(base, 'myapp');
}
```

---

## Verification checklist for macOS Test Isolation

- [ ] Does your global config/state resolution code branch on `darwin`?
- [ ] If yes, does it allow overriding via `XDG_CONFIG_HOME` or a dedicated test environment variable (e.g. `MYAPP_CONFIG_DIR`) first?
- [ ] Do E2E and integration tests clean up their isolated temporary config folders?
- [ ] Is `process.env` fully isolated per test run to prevent environment pollution from leaking into concurrent test threads?
