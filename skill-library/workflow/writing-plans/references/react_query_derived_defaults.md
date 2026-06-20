# React & React Query Derived Defaults Pattern (ESLint & Performance Optimization)

## Overview

When developing React applications driven by asynchronous server state (such as fetching data feeds via TanStack React Query `useQuery`), we often need to default a dropdown selector or state filter to a specific "active" or "default" item returned by the server (e.g., defaulting a season filter dropdown to the loaded `is_active` season).

## The Anti-Pattern: `useEffect` State Syncing

A common but fragile approach is to listen to the query's completion inside a `useEffect` hook and update a local `useState` variable:

```tsx
// ❌ ANTI-PATTERN: Creates duplicate render cycles, stale states, and triggers ESLint errors
const [selectedSeasonId, setSelectedSeasonId] = useState("");
const { data: seasonsData } = useQuery({ queryKey: ["seasons"], queryFn: weeksApi.listSeasons });

const seasons = seasonsData?.seasons || [];
const activeSeason = seasons.find(s => s.is_active);

useEffect(() => {
  if (activeSeason && !selectedSeasonId) {
    setSelectedSeasonId(activeSeason.id);
  }
}, [seasonsData, activeSeason, selectedSeasonId]); // Trips react-hooks/exhaustive-deps & set-state-in-effect
```

### Why this is bad
1. **Double Renders:** Triggering `setState` inside `useEffect` right after a query resolves forces React to execute an immediate second render pass, degrading user performance.
2. **Stale State Desyncs:** If the server data changes out-of-band (e.g., another season is marked active), the local state remains pinned to the stale value until the effect executes again.
3. **Compiler Warnings:** It frequently triggers strict ESLint rules such as `react-hooks/exhaustive-deps` or custom hooks state-setting rules, failing automated code-quality pipelines.

---

## The Gold-Standard Solution: Derived Values

Instead of synchronizing the server default into a local state, maintain the state as a **pure override filter** (`""` representing "no manual selection yet"), and compute the **effective** active value dynamically as a derived value during the render pass:

```tsx
// ✅ GOLD-STANDARD: Zero extra renders, instantly responsive, 100% type-safe, and compiler-clean
const [selectedSeasonId, setSelectedSeasonId] = useState(""); // "" = use server default

const { data: seasonsData } = useQuery({ queryKey: ["seasons"], queryFn: weeksApi.listSeasons });

const seasons = seasonsData?.seasons || [];

// Derive the effective ID directly during the render pass!
const effectiveSeasonId = selectedSeasonId || seasons.find((s) => s.is_active)?.id || "";

// Feed the effective ID into subsequent scoped queries safely
const { data: messagesData } = useQuery({
  queryKey: ["messages", effectiveSeasonId],
  queryFn: () => messagesApi.list(effectiveSeasonId),
  enabled: !!effectiveSeasonId, // Only query when effective ID is resolved!
});
```

### Why this works perfectly
1. **Zero Side Effects:** No `useEffect` is required. The dropdown defaults itself naturally to the active season without any additional state mutations.
2. **Instant Responsiveness:** As soon as the user selects a different season in the dropdown, `selectedSeasonId` is updated, the derived `effectiveSeasonId` switches instantly, and React Query triggers the scoped feed query immediately.
3. **Pristine Quality Gates:** Eliminates all hooks-related compilation or linter warnings, guaranteeing a 100% green build.

---

## UI Binding Pattern

Bind the selector's `value` attribute to the derived `effectiveSeasonId` and its `onChange` handler to the state setter `setSelectedSeasonId`:

```tsx
<select
  value={effectiveSeasonId}
  onChange={(e) => setSelectedSeasonId(e.target.value)}
  className="rounded-md border-gray-300 py-1.5 pl-3 pr-10 text-sm focus:border-blue-500"
>
  {seasons.map((s) => (
    <option key={s.id} value={s.id}>
      {s.year} Season {s.is_active ? "(Active)" : ""}
    </option>
  ))}
</select>
```
