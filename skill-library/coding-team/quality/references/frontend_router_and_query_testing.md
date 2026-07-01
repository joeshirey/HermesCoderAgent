# Frontend Router & Query Testing Best Practices

Guidelines and patterns for writing robust, flaky-free unit and integration tests in React with Vitest, React Testing Library (RTL), React Router, and React Query.

---

## 1. React Router Context Errors (`basename` Destructure Failure)

### The Symptom
When rendering a component that uses React Router hooks or components (like `<Link>`, `<NavLink>`, `useNavigate()`, `useParams()`), the test run crashes with:
```
TypeError: Cannot destructure property 'basename' of 'React.useContext(...)' as it is null.
```

### The Cause
React Router components and hooks require a router provider context to exist in the component tree. Direct rendering (e.g. `render(<MyComponent />)`) fails because no context is present.

### The Solution
Import `MemoryRouter` from `react-router-dom` and wrap your test component (or its query wrapper) in it. This isolates the navigation context and satisfies all routing dependencies seamlessly:

```typescript
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import MyComponent from "./MyComponent";

// Using a custom wrapper function for QueryClient + Router
const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </MemoryRouter>
  );
};

// In your test case:
render(<MyComponent />, { wrapper: createWrapper() });
```

---

## 2. React Query Async Timing Pitfall (The RTL `waitFor` Trap)

### The Symptom
A test is written to verify that the page displays a loading fallback when no data is returned. However, the test passes immediately even when mocks *with data* are provided, or it behaves nondeterministically.

### The Cause
React Query queries (like `useQuery`) begin in a `loading` / `pending` state during the initial component render. At this stage, `query.data` is `undefined`. If your component has a fallback:
```typescript
if (!data) {
  return <div>No data available.</div>;
}
```
Then during the very first render, `"No data available."` is painted. If your test asserts:
```typescript
await waitFor(() => {
  expect(screen.getByText("No data available.")).toBeInTheDocument();
});
```
This assertion is **satisfied instantly on the initial render** before the mocked promise resolves! The test passes too early and never actually waits for the mock to resolve.

### The Solution
To robustly test resolved states:
1. **Always wait for a unique resolved-state element first** to force React Testing Library to wait for the mocked query promise to settle:
   ```typescript
   // Wait for the resolved dashboard header to appear
   await waitFor(() => {
     expect(screen.getByText("Active Picks Dashboard")).toBeInTheDocument();
   });
   
   // Now safe to run subsequent assertions
   expect(screen.queryByText("No data available.")).not.toBeInTheDocument();
   ```
2. Alternatively, verify that the loading fallback *disappears* before checking resolved items:
   ```typescript
   await waitForElementToBeRemoved(() => screen.getByText("Loading..."));
   ```

---

## 3. Duplicate Text Query Errors ("Found multiple elements with text...")

### The Symptom
RTL's `screen.getByText("My CTA")` throws an error:
```
TestingLibraryElementError: Found multiple elements with the text: My CTA
```

### The Cause
This occurs when the page displays identical text strings in different places—for example, in a top notifications banner and inside an empty-state body card.

### The Solution
1. **Assert Multiple Occurrences Explicitly** using `screen.getAllByText` to verify both elements are rendered as intended:
   ```typescript
   expect(screen.getAllByText("View Results").length).toBe(2);
   ```
2. **Target Specific Elements by Role & Accessibility Name** to isolate a specific button or link:
   ```typescript
   expect(screen.getByRole("link", { name: "View Results" })).toBeInTheDocument();
   ```

---

## 4. Mocking Missing JSDOM Layout APIs (e.g. `scrollIntoView`)

### The Symptom
When testing a component that triggers layout or positioning helpers (such as auto-scrolling to the bottom of a chat thread or moving focus), the test crashes with:
```
TypeError: Element.prototype.scrollIntoView is not a function
```

### The Cause
JSDOM is a lightweight, headless DOM representation designed for speed, so it does not simulate full CSS layout, layouts math, or pixel positioning. As a result, it does not implement standard window and element layout methods like `scrollIntoView()`, `scrollTo()`, or `getBoundingClientRect()` natively.

### The Solution
Implement dummy spy mocks for any missing layout APIs in your test setup file (e.g., `frontend/src/test/setup.ts` or at the very top of your test file):

```typescript
import { vi } from "vitest";

// Mock missing JSDOM layout method
Element.prototype.scrollIntoView = vi.fn();
```

---

## 5. ESLint custom hook dependency stabilization (Memoizing Empty Fallback Arrays)

### The Symptom
ESLint raises a dependency warning inside a `useEffect` hook block:
```
warning: The 'messages' logical expression could make the dependencies of useEffect Hook change on every render.
```

### The Cause
Initializing a fallback empty array using an inline logical or nullish coalescing operator in the render body:
```typescript
const messages = messagesQuery.data?.messages ?? [];
```
creates a brand-new array literal reference `[]` on every single render cycle if the query hasn't returned data yet. If this variable is passed as a dependency to a `useEffect` hook, the reference identity check changes on every render, triggering the effect repeatedly.

### The Solution
Use `useMemo` to stabilize the reference identity of the empty array fallback:
```typescript
const messages = useMemo(() => messagesQuery.data?.messages ?? [], [messagesQuery.data?.messages]);
```
This ensures that the reference identity remains identical as long as the underlying query data has not changed, resolving both ESLint and potential infinite rendering loop leaks.

---

## 6. CSS `:nth-of-type(N)` Query Selector Parent Pitfalls

### The Symptom
Querying elements (such as date or datetime inputs) in Jest/Vitest using layout query selectors like:
```typescript
container.querySelector('input[type="date"]:nth-of-type(2)')
```
returns `null`, crashing the test with:
```
Error: Unable to fire a "change" event - please provide a DOM element.
```

### The Cause
The `:nth-of-type(N)` CSS pseudo-class selects an element that is the Nth child of that type **within its direct parent element**. If your React components wrap input fields in individual styling `div` containers (common for forms and layouts), each input is actually the *first* child of its wrapper `div`. Because no single parent element has more than one `input[type="date"]`, `:nth-of-type(2)` has no match and returns `null`.

### The Solution
Query elements globally using `container.querySelectorAll` and target them by array index, which is immune to nested wrapper divs:
```typescript
// Select all date inputs globally in the rendered form
const dateInputs = container.querySelectorAll('input[type="date"]');

// Target by array index
fireEvent.change(dateInputs[0] as HTMLInputElement, { target: { value: '2026-06-10' } }); // Start Date
fireEvent.change(dateInputs[1] as HTMLInputElement, { target: { value: '2026-06-13' } }); // End Date

// Target datetime-local inputs uniquely
fireEvent.change(container.querySelector('input[type="datetime-local"]') as HTMLInputElement, { target: { value: '2026-06-10T08:00' } });
```

---

## 7. Vitest `Mock` Type Assertions (Bypassing `no-explicit-any` ESLint rules)

### The Symptom
Mocking external services or custom hooks in tests using type assertions like:
```typescript
(useAuth as any).mockReturnValue({ isAdmin: true });
```
triggers TypeScript/ESLint warnings or errors:
```
Unexpected any. Specify a different type  @typescript-eslint/no-explicit-any
```

### The Cause
Strict static analysis quality gates block explicit uses of the `any` type (like `as any`) to guarantee type safety across the application.

### The Solution
Import `Mock` from `vitest` and typecast your mocked functions as `as Mock` instead of `as any`. This satisfies the compiler, provides type safety, and satisfies all ESLint linting constraints:
```typescript
import { vi, type Mock } from 'vitest';
import { useAuth } from '../../hooks/useAuth';

// Mock values type-safely and with zero ESLint warnings
(useAuth as Mock).mockReturnValue({
  user: { id: 'admin1', email: 'admin@b.com' },
  isAdmin: true,
  isAuthenticated: true,
});
```

---

## 8. React Responsive Auto-Select State Loops (Mobile navigation back-buttons)

### The Symptom
On mobile viewports, clicking a back button designed to navigate back to a list panel (e.g. "← Folders" or "← List" that sets a selection state like `setSelectedFolder(null)`) appears to do nothing and the pane doesn't switch. However, the button's click handler is correctly wired up, and no exceptions are logged.

### The Cause
An auto-selection `useEffect` designed to select the first list item on desktop once data loads is executing unconditionally on all screen sizes:
```typescript
useEffect(() => {
  if (!selectedFolder && folders.length > 0) {
    setSelectedFolder(folders[0]);
  }
}, [folders, selectedFolder]);
```
On mobile viewports, when the user clicks the back button, `selectedFolder` becomes `null`. This state update instantly triggers the auto-selection `useEffect` on the next render tick. Because `folders` are already loaded, the hook instantly re-selects the first folder `folders[0]`, resetting the mobile viewport's pane view back to `'topics'` in a split-second.

### The Solution
1. **Define a responsive viewport width state listener** at the top of the component (e.g., using `window.innerWidth` and matching Tailwind's `md` breakpoint `768px`):
   ```typescript
   const [isDesktop, setIsDesktop] = useState(false);

   useEffect(() => {
     if (typeof window !== 'undefined') {
       const handleResize = () => setIsDesktop(window.innerWidth >= 768);
       handleResize();
       window.addEventListener('resize', handleResize);
       return () => window.removeEventListener('resize', handleResize);
     }
   }, []);
   ```
2. **Guard the desktop auto-select hook** with the responsive `isDesktop` boolean:
   ```typescript
   useEffect(() => {
     if (isDesktop && !selectedFolder && folders.length > 0) {
       setSelectedFolder(folders[0]);
     }
   }, [folders, selectedFolder, isDesktop]);
   ```

---

## 9. Vitest Context Hook Mocking & Destructured Properties Mismatch

### The Symptom
After destructuring a property directly from a custom context hook (e.g. `const { user, isAdmin } = useAuth();`), the component crashes or behaves as though the property is `undefined` in your unit tests, even when the mock `user` has the property set inside the mock payload.

### The Cause
The Vitest mock of the custom hook is only returning a subset of properties (like just `{ user: mockUser }`), meaning the destructured top-level properties (like `isAdmin`) are undefined during the test's execution.

### The Solution
Always align your Vitest hook mocks to return all destructured fields at the top-level of the mock response payload:
```typescript
// If the component destructures: const { user, isAdmin } = useAuth();
// Ensure the mock returns both fields at the root of the mock returned object:
vi.mock('../hooks/useAuth', () => ({
  useAuth: () => ({
    user: mockAuthUser,
    isAdmin: mockAuthUser.isAdmin // Explicitly return destructured root properties
  }),
}));
```

---

## 10. Testing Negative Assertion Guards (False Positive Assertions)

### The Symptom
A test is written to verify that clicking a disabled or restricted element does *not* trigger a state change or UI expansion (e.g., verifying that a row expansion guard prevents displaying sub-details). The test passes successfully, but if you deliberately break the guard in the component, the test *still* passes.

### The Cause
This occurs when the negative assertion verifies the absence of content that would be absent anyway, regardless of whether the guard succeeded. For example, if you click a disabled row for "Player Five" (which has no sub-details or is empty) and assert that "Tiger Woods" (who belongs only to "Player One's" details) is not in the document, the assertion will always hold true because "Tiger Woods" is not associated with "Player Five" in the first place! The test can never fail, creating a false sense of security.

### The Solution
When asserting negative behaviors or verifying guards that block UI updates:
1. **Target Content Specific to the Action:** Assert the absence of content that *only* exists or *would* appear if the action on that specific element succeeded (e.g., a specific sub-detail or unique ID belonging to that exact row's model).
2. **Deliberately Red-Green Verify:** Temporarily comment out or invert the guard in your component code to verify that the test fails (RED state) before confirming it passes when the guard is active (GREEN state).

---

## 11. Asserting Responsive Tailwind Variants (Breakpoint Prefix Pitfall)

### The Symptom
A test is written to verify that a mobile responsive layout hides or limits an element (e.g., using `max-h-full sm:max-h-[85vh]`). However, when asserting the presence of the class string:
```typescript
expect(panel.className).toContain('max-h-[85vh]');
```
The test passes, but in reality, the modal is displaying full height (`max-h-full`) on mobile, which violates the mobile spec!

### The Cause
Using a broad `.toContain('max-h-[85vh]')` matches any substring inside the class attribute. If the actual class list is `max-h-full sm:max-h-[85vh]`, the substring `'max-h-[85vh]'` matches the desktop responsive variant `sm:max-h-[85vh]` perfectly. Because jsdom does not evaluate media queries or compute layout, the test passes successfully, giving false confidence that the restriction applies globally rather than only on desktop.

### The Solution
When testing responsive Tailwind layouts in jsdom, always include the full breakpoint prefix in your class assertions:
```typescript
// Assert the mobile-first class
expect(panel.className).toContain('max-h-full');

// Assert the desktop responsive class explicitly with its breakpoint prefix
expect(panel.className).toContain('sm:max-h-[85vh]');

// Assert the exact unprefixed class is NOT present to prevent global overrides
expect(panel.className).not.toContain(' max-h-[85vh]');
```
By explicitly asserting both the mobile-first behavior and the prefixed desktop override, you ensure that the component styling maintains correct responsive behavior across viewports.

---

## 12. Extracting Duplicated Complex Assertions (Dry Test Sweeps)

### The Symptom
Testing multiple paths that lead to the same complex UI element (such as testing both the Reply Composer and the Edit Message forms opening the same Giphy Search Modal) results in large, copy-pasted blocks of DOM traversal and layout class assertions. This duplicates logic, bloats the test file, and makes future design updates highly tedious to maintain.

### The Cause
Both flows open the exact same shared sub-component under the hood, but because they mount in different parent contexts (e.g., different forms or overlays), developers copy-paste the entire validation chain to confirm the layout constraints hold in both places.

### The Solution
Extract the complex DOM traversal and structural assertions into a dedicated, reusable verification helper function within the test file. This keeps the test suite DRY, ensures absolute consistency across execution paths, and simplifies future class/layout changes:

```typescript
const verifyGiphyModalLayout = (headingText = 'Search Giphy GIFs 🎬') => {
  const heading = screen.getByText(headingText);
  const panel = heading.parentElement!.parentElement!;
  
  // Assert outer container constraints
  expect(panel.className).toContain('overflow-hidden');
  expect(panel.className).toContain('max-h-full');
  
  // Assert search row styling
  const searchInput = screen.getByRole('textbox', { name: 'Search Giphy query' });
  const searchRow = searchInput.parentElement!;
  expect(searchRow.className).toContain('shrink-0');
  
  // Assert scroll wrapper styling
  const innerWrapper = searchRow.nextElementSibling as HTMLElement;
  expect(innerWrapper.className).toContain('flex-1');
  expect(innerWrapper.className).toContain('min-h-0');
  expect(innerWrapper.className).toContain('overflow-y-auto');
};

// In your test cases:
it('keeps modal within layout constraints in the compose flow', async () => {
  // Open modal in compose flow...
  verifyGiphyModalLayout();
});

it('keeps modal within layout constraints in the edit flow', async () => {
  // Open modal in edit flow...
  verifyGiphyModalLayout();
});
```

---

## 13. React Testing Library `waitFor` Hangs with Vitest Fake Timers

### The Symptom
After enabling fake timers in a test suite using `vi.useFakeTimers()`, tests that call `waitFor` or `waitForElementToBeRemoved` suddenly time out (e.g. after 5000ms) even though all mocks are configured correctly and the exact same tests pass perfectly with real timers.

### The Cause
React Testing Library's asynchronous waiters (like `waitFor`) rely on real timing functions (specifically `setTimeout` and `setInterval`) to poll the DOM for changes over time. When `vi.useFakeTimers()` is invoked without arguments, Vitest fakes **all** timing APIs (`setTimeout`, `setInterval`, `clearTimeout`, `clearInterval`, `Date`, etc.). Because the fake clock does not advance automatically during the synchronous execution of `waitFor`, the polling intervals never fire, causing the test to freeze and time out.

### The Solution
Instead of faking all timers globally, instruct Vitest to fake **only** the `Date` class. This pins the system clock for logic-heavy calculations (like `new Date()`) while leaving real scheduling timers untouched, allowing `waitFor`'s polling mechanism to execute normally on the real clock:

```typescript
beforeEach(() => {
  // Fake ONLY the system clock/Date, leaving setTimeout/setInterval intact
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-06-28T12:00:00Z'));
  vi.clearAllMocks();
});

afterEach(() => {
  // Restore real timers after each test case
  vi.useRealTimers();
});
```
