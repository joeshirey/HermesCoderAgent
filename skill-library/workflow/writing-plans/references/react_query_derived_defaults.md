# React & React Query Derived Defaults Pattern (ESLint & Performance Optimization)

## Overview

When developing React applications driven by asynchronous server state (such as fetching data feeds via TanStack React Query `useQuery`), we often need to default a dropdown selector or state filter to a specific "active" or "default" item returned by the server (e.g., defaulting an event filter dropdown to the loaded `is_active` event).

## The Anti-Pattern: `useEffect` State Syncing

A common but fragile approach is to listen to the query's completion inside a `useEffect` hook and update a local `useState` variable:

```tsx
// ❌ ANTI-PATTERN: Creates duplicate render cycles, stale states, and triggers ESLint errors
const [selectedEventId, setSelectedEventId] = useState("");
const { data: eventsData } = useQuery({ queryKey: ["events"], queryFn: eventsApi.listEvents });

const events = eventsData?.events || [];
const activeEvent = events.find(s => s.is_active);

useEffect(() => {
  if (activeEvent && !selectedEventId) {
    setSelectedEventId(activeEvent.id);
  }
}, [eventsData, activeEvent, selectedEventId]); // Trips react-hooks/exhaustive-deps & set-state-in-effect
```

### Why this is bad
1. **Double Renders:** Triggering `setState` inside `useEffect` right after a query resolves forces React to execute an immediate second render pass, degrading user performance.
2. **Stale State Desyncs:** If the server data changes out-of-band (e.g., another event is marked active), the local state remains pinned to the stale value until the effect executes again.
3. **Compiler Warnings:** It frequently triggers strict ESLint rules such as `react-hooks/exhaustive-deps` or custom hooks state-setting rules, failing automated code-quality pipelines.

---

## The Gold-Standard Solution: Derived Values

Instead of synchronizing the server default into a local state, maintain the state as a **pure override filter** (`""` representing "no manual selection yet"), and compute the **effective** active value dynamically as a derived value during the render pass:

```tsx
// ✅ GOLD-STANDARD: Zero extra renders, instantly responsive, 100% type-safe, and compiler-clean
const [selectedEventId, setSelectedEventId] = useState(""); // "" = use server default

const { data: eventsData } = useQuery({ queryKey: ["events"], queryFn: eventsApi.listEvents });

const events = eventsData?.events || [];

// Derive the effective ID directly during the render pass!
const effectiveEventId = selectedEventId || events.find((s) => s.is_active)?.id || "";

// Feed the effective ID into subsequent scoped queries safely
const { data: messagesData } = useQuery({
  queryKey: ["messages", effectiveEventId],
  queryFn: () => messagesApi.list(effectiveEventId),
  enabled: !!effectiveEventId, // Only query when effective ID is resolved!
});
```

### Why this works perfectly
1. **Zero Side Effects:** No `useEffect` is required. The dropdown defaults itself naturally to the active event without any additional state mutations.
2. **Instant Responsiveness:** As soon as the user selects a different event in the dropdown, `selectedEventId` is updated, the derived `effectiveEventId` switches instantly, and React Query triggers the scoped feed query immediately.
3. **Pristine Quality Gates:** Eliminates all hooks-related compilation or linter warnings, guaranteeing a 100% green build.

---

## UI Binding Pattern

Bind the selector's `value` attribute to the derived `effectiveEventId` and its `onChange` handler to the state setter `setSelectedEventId`:

```tsx
<select
  value={effectiveEventId}
  onChange={(e) => setSelectedEventId(e.target.value)}
  className="rounded-md border-gray-300 py-1.5 pl-3 pr-10 text-sm focus:border-blue-500"
>
  {events.map((s) => (
    <option key={s.id} value={s.id}>
      {s.name} {s.is_active ? "(Active)" : ""}
    </option>
  ))}
</select>
```
