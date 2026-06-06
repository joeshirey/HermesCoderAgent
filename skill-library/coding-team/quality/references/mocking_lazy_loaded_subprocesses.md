# Mocking Lazy-Loaded Subprocesses & Component Isolation

When testing component adapters or client integrations that dynamically lazy-load external SDKs or wrap command-line subprocesses, improper isolation can cause tests to execute slow real-world operations, hang indefinitely, or trigger standard test timeouts (e.g. 5000ms vitest timeouts).

This reference details the "lazy-loaded process leak" pitfall, its diagnostic symptoms, and a robust mock-injection pattern to solve it.

---

## The Pitfall: Leaky Lazy-Loading Constructor Fallbacks

To keep core package imports lightweight, constructors often lazy-load heavy external dependencies (such as `@github/copilot-sdk`) only when a pre-built provider isn't explicitly supplied:

```typescript
// Production Code: Pluggable provider with lazy fallback
export class SquadClient {
  private provider: SquadProvider;

  constructor(options: SquadClientOptions = {}) {
    if (options.provider) {
      this.provider = options.provider;
    } else {
      // Lazy load standard provider if none is injected
      const { CopilotProvider } = require('./providers/copilot-provider.js');
      this.provider = new CopilotProvider(options);
    }
  }
}
```

### Why This Fails in Test Suites

1. **Spawning Real Processes:** During testing, if a test instantiates `new SquadClient({ autoReconnect: false })` without passing a mock provider in the options, the constructor falls back to `CopilotProvider`, which attempts to start up and connect to a real background CLI command-line binary.
2. **Missing Global Mocks:** If the test file does not globally stub out `vi.mock('@github/copilot-sdk')` or command-line execution, the test suite will block on real OS subprocess spawning or socket handshakes.
3. **Severe Symptoms:**
   - The test hangs and eventually exits with: `Error: Test timed out in 5000ms.`
   - In environments without the real command-line binary installed (e.g., lightweight containerized runners or specific test hosts), the entire test runner crashes with `spawn ENOENT` errors.

---

## The Safe Testing Patterns

To prevent lazy-loaded component leaks, apply one of the following two testing strategies:

### Pattern A: Explicit Mock Provider Injection (Highly Preferred)

Rather than relying on global stubs, inject a lightweight mock provider into every local unit and connection-lifecycle test. This completely isolates your component under test and bypasses any lazy-loading logic entirely.

```typescript
// Safe Test: Complete mock provider injection
import { describe, it, expect, vi } from 'vitest';
import { SquadClient } from '@bradygaster/squad-sdk/client';

function createMockProvider() {
  const mocks = {
    connect: vi.fn().mockResolvedValue(undefined),
    createSession: vi.fn().mockResolvedValue({ sessionId: 'session-1' }),
  };
  return { name: 'mock-provider', ...mocks, _mocks: mocks };
}

describe('SquadClient', () => {
  it('should handle session creation errors gracefully', async () => {
    const mockProvider = createMockProvider();
    const client = new SquadClient({ provider: mockProvider, autoReconnect: false });
    await client.connect();

    // Force error behavior locally and instantly
    mockProvider._mocks.createSession.mockRejectedValue(new Error('onPermissionRequest is required'));

    await expect(client.createSession()).rejects.toThrow('onPermissionRequest is required');
  });
});
```

### Pattern B: Mocking the External Dependency Globally

If you must test the lazy-loading path specifically (e.g., verifying that the fallback logic instantiates correctly), you must explicitly mock the external module at the absolute top of your test file to stub out subprocess spawning:

```typescript
import { vi } from 'vitest';

// Safe Test: Stub the lazy-loaded module before any imports
vi.mock('@github/copilot-sdk', () => {
  return {
    CopilotClient: vi.fn().mockImplementation(() => {
      return {
        start: vi.fn().mockResolvedValue(undefined),
        createSession: vi.fn().mockResolvedValue({ sessionId: 'session-1' }),
      };
    }),
  };
});
```

---

## Verification Checklist

- [ ] Does the class constructor support lazy-loading or default fallbacks that spawn subprocesses or open network connections?
- [ ] Are unit/integration tests injecting a mocked provider to bypass fallback lazy-loading paths?
- [ ] If a test is failing due to a 5000ms timeout, check if an unmocked background subprocess is being spawned under the hood.
