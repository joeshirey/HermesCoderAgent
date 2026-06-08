# SQLAlchemy Boolean Query Linter Workarounds (Ruff E712 / PEP 8)

When developing SQLAlchemy or SQLModel query expressions, Python linters (like **Ruff `E712`** or PEP 8 checkers) frequently flag boolean equality checks as code quality violations:

```python
# Ruff flags E712: "Avoid equality comparisons to True/False; use 'is_active' or 'not is_active'"
select(Season).where(Season.is_active == False)
```

## The Failure Mode

If you follow the linter's naive recommendation and rewrite it using Python's logical `not` or bare attribute evaluation:

```python
# BROKEN: compiles to static False / where(False)
select(Season).where(not Season.is_active)
```

### Why it fails

SQLAlchemy overloads standard Python operators (like `==`, `!=`, `<`, `>`) to return SQL expression-building binary clauses. However, Python's logical `not` and truthiness evaluation **cannot be overloaded**.

When Python evaluates `not Season.is_active`, it evaluates the class attribute's truthiness at import/query assembly time. Since the attribute object exists, it evaluates to `True`, so `not` returns `False`. The query compiles statically to:

```sql
SELECT ... WHERE false;
```

This query returns an empty set, resulting in silent query filtering failures or broken tests.

---

## The Safe, Linter-Compliant Workarounds

To satisfy both standard Python linting rules (Ruff E712) and maintain full SQL compilation fidelity, apply one of the following SQLAlchemy-idiomatic patterns:

### Option A: Use `.is_()` (Recommended)

The `.is_()` method explicitly compiles to SQL `IS TRUE` or `IS FALSE` checks and is 100% compliant with Python linters out-of-the-box.

```python
# 100% PASS (Linter Green + SQL Green)
select(Season).where(Season.is_active.is_(False))
select(Season).where(Season.is_active.is_(True))
```

### Option B: Use Bitwise Inversion `~`

For negative checks, you can use SQLAlchemy's bitwise inversion operator `~`, which is cleanly overloaded.

```python
# 100% PASS (Linter Green + SQL Green)
select(Season).where(~Season.is_active)
```

### Option C: Inline Comment Suppression

If you must use the standard equality operator (e.g., to support specific dialects or strict literal equality checks), suppress the specific linter check inline.

```python
# noqa: E712
select(Season).where(Season.is_active == False)  # noqa: E712
```
