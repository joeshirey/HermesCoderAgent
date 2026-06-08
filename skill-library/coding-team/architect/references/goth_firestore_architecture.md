# GOTH Stack & GCP Firestore Architecture Notes

Condensed architectural patterns and lessons learned during GOTH stack (Go, Templ, htmx, Tailwind CSS) development and native GCP Firestore integration.

---

## 1. Local Developer Watch Orchestration

When scaffolding a highly interactive GOTH stack, developers run three separate background watchers concurrently during local development:

- **Templ watcher**: `templ generate --watch`
- **Tailwind CSS watcher**: `npx tailwindcss -i ./assets/css/input.css -o ./static/css/styles.css --watch`
- **Go server watcher**: `air` (live reloading)

### Clean Process Trapping Pattern (Makefile)

Running these concurrently in a single foreground terminal target usually leaves orphaned processes on exit. Solve this programmatically using a shell `trap 'kill 0'` handler in your `Makefile`:

```makefile
.PHONY: watch-templ watch-tailwind watch-server dev

watch-templ:
 templ generate --watch

watch-tailwind:
 npx tailwindcss -i ./assets/css/input.css -o ./static/css/styles.css --watch

watch-server:
 air

dev:
 @echo "Starting GOTH development environment..."
 @trap 'kill 0' INT TERM EXIT; \
 make watch-templ & \
 make watch-tailwind & \
 make watch-server & \
 wait
```

*Key benefit:* Hitting `Ctrl+C` cleanly propagates the interrupt signal to all background jobs, preventing terminal locks or port binding conflicts.

---

## 2. GCP Firestore Named Database Integration

By default, the Google Cloud Go SDK client connects to the standard `(default)` database in a project. In modern GCP configurations with multiple native-mode databases, developers should avoid using the default `firestore.NewClient` constructor.

### Named Database Targeting

Use `NewClientWithDatabase` to bind the client specifically to a custom-named database (e.g., `restres`):

```go
package db

import (
 "context"
 "fmt"
 "cloud.google.com/go/firestore"
)

type FirestoreRepository struct {
 client *firestore.Client
}

func NewFirestoreRepository(ctx context.Context, projectID, databaseID string) (*FirestoreRepository, error) {
 // Securely binds to the named database
 client, err := firestore.NewClientWithDatabase(ctx, projectID, databaseID)
 if err != nil {
  return nil, fmt.Errorf("failed to create firestore client: %w", err)
 }
 return &FirestoreRepository{client: client}, nil
}
```

### Decoupled Resiliency Fallback

To support local offline development without requiring active cloud credentials or dealing with Datastore Mode constraints, implement an in-memory `MockRepository` fallback in `main.go`:

```go
 databaseID := os.Getenv("FIRESTORE_DATABASE")
 if databaseID == "" {
  databaseID = "restres"
 }

 var repo db.ReservationRepository
 var err error
 if os.Getenv("USE_MOCK_DB") == "true" {
  log.Println("Forcing fallback to MockRepository")
  repo = db.NewMockRepository()
 } else {
  repo, err = db.NewFirestoreRepository(ctx, projectID, databaseID)
  if err != nil {
   log.Printf("Warning: Firestore failed, falling back to MockRepository: %v", err)
   repo = db.NewMockRepository()
  }
 }
```

---

## 3. Native Firestore Composite Indexes

When running queries in Native Firestore that filter on one field and sort on another (e.g. `Where("date", "==", d).OrderBy("time", Asc)`), Firestore requires a **composite index**.

### Error Signal (FailedPrecondition)

If the index is missing, Firestore returns a `FailedPrecondition` RPC error during query execution (not on client instantiation):

```
rpc error: code = FailedPrecondition desc = The query requires an index. You can create it here: https://console.firebase.google.com/v1/r/project/<project>/firestore/databases/<database>/indexes?create_composite=...
```

### Workaround

1. **Click the URL**: The error payload contains an auto-generated URL specifically encoded for your query.
2. **Auto-Generate**: Opening the URL in a browser logged into the target GCP account pre-populates the index fields automatically in the GCP Firebase Console.
3. **Execute**: Click "Create index" and wait 1–2 minutes for the status to turn active.
