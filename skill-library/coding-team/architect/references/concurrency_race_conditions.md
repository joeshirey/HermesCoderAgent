# Concurrency & Distributed State Race Conditions

In asynchronous, event-driven, or multi-component systems (e.g., API web servers communicating with Pub/Sub subscribers, background workers, or external analytical stores like Google BigQuery), **read-compute-write cycles** in application memory are highly susceptible to race conditions.

## 1. The Read-Compute-Write Concurrency Bug

### The Bug

A common pattern where an application service fetches remote records, calculates a aggregate value (such as a mathematical mean or total score) in local memory, and updates a database row with the calculated result:

```go
func (s *HackathonService) AddEvaluation(eval *models.Evaluation) error {
    // 1. Fetch all past evaluations for the project
    evals, err := s.evalRepo.GetByProjectID(eval.ProjectID)
    
    // 2. Compute mathematical mean in application memory
    var total float64
    for _, e := range evals {
        total += e.TotalScore
    }
    average := total / float64(len(evals))
    
    // 3. Write average back to DB
    return s.projectRepo.UpdateScore(eval.ProjectID, average)
}
```

### Why It Fails

If multiple distinct scorers (e.g., an automated agent container and an AI background judge) finish their evaluations at nearly the same time, they will trigger this handler **concurrently**:

1. **Thread A** reads the evaluations from the database (obtains 2 rows).
2. **Thread B** reads the evaluations from the database (obtains the same 2 rows).
3. **Thread A** computes the average and writes it back to the database.
4. **Thread B** computes the average based on the old 2 rows (even though Thread A has just added a 3rd) and overwrites Thread A's correct score with a stale, incorrect average.

This leads to silent data corruption and incorrect system aggregates.

---

## 2. Prevention Strategies

### A. Atomic Database Operations (Preferred)

Delegate mathematical computation and state changes directly to the database engine. Databases are built to execute queries atomically using locks or transactional constraints:

```sql
-- Shift computation to the DB
UPDATE projects 
SET score = (SELECT AVG(total_score) FROM evaluations WHERE project_id = $1)
WHERE id = $1;
```

### B. Distributed Lock / Mutexes

If the computation must remain in application memory, wrap the critical read-compute-write sequence inside a lock:

* **For single-instance services:** Use a language-native mutual exclusion lock (e.g. `sync.Mutex` in Go or threading locks in Python).
* **For distributed, multi-instance services:** Use a distributed lock coordinator (e.g. Redis/Redlock, Consul, or database row locks like `SELECT FOR UPDATE` in PostgreSQL).

### C. Pessimistic / Optimistic Locking

Ensure that the database row cannot be updated if another process has read it since the current transaction began:

* **Optimistic locking:** Add a `version` or `updated_at` column. Ensure the update query only succeeds if the version hasn't changed, returning an error to retry the transaction otherwise.

---

## 3. Architecture Review Guide

When auditing multi-component distributed architectures, look for these design smells:

* **State in multiple places:** The same data is stored and updated in distinct systems (e.g., BigQuery and SQLite/PostgreSQL) without a single system of record.
* **In-memory recalculations:** Aggregates are recalculated inside HTTP handlers instead of via database transactions or asynchronous event aggregators.
* **Lack of watchdogs:** Long-running `RUNNING` tasks lack a background monitor or self-expiring timeout, causing jobs to hang indefinitely when workers crash or get evicted.
