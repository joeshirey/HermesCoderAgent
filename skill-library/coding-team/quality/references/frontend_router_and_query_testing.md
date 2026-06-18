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
