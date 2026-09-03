# Architecture — Razor402

## Sequence Diagrams

### Happy Path (I1: 402 → settle → fulfil)

```
Agent                Gateway              Razorpay          Merchant
  │                     │                     │                │
  │  POST /provision/X  │                     │                │
  │────────────────────>│                     │                │
  │  402 + challenge    │                     │                │
  │<────────────────────│                     │                │
  │                     │                     │                │
  │  POST /provision/X  │                     │                │
  │  X-PAYMENT: JWS     │                     │                │
  │────────────────────>│                     │                │
  │                     │  verify proof       │                │
  │                     │  server gate        │                │
  │                     │  → VERIFIED         │                │
  │                     │                     │                │
  │                     │  create_order(cid)  │                │
  │                     │────────────────────>│                │
  │                     │  debit(order, cid)  │                │
  │                     │────────────────────>│                │
  │                     │  → SETTLED          │                │
  │                     │                     │                │
  │                     │  POST /provision/X                   │
  │                     │────────────────────────────────────>│
  │                     │  provisioning payload               │
  │                     │<────────────────────────────────────│
  │                     │  → FULFILLED        │                │
  │                     │                     │                │
  │  200 + payload      │                     │                │
  │  X-PAYMENT-RESPONSE │                     │                │
  │<────────────────────│                     │                │
```

### Compensation (I4: settle ok → merchant fails → refund)

```
Agent                Gateway              Razorpay          Merchant
  │                     │                     │                │
  │  (after SETTLED)    │                     │                │
  │                     │  POST /provision/X                   │
  │                     │────────────────────────────────────>│
  │                     │  500 (crash/hang)                   │
  │                     │<────────────────────────────────────│
  │                     │  → COMPENSATING     │                │
  │                     │                     │                │
  │                     │  list_refunds(pid)  │                │
  │                     │────────────────────>│                │
  │                     │  (none existing)    │                │
  │                     │<────────────────────│                │
  │                     │  refund(pid, paise) │                │
  │                     │────────────────────>│                │
  │                     │  → COMPENSATED      │                │
  │                     │                     │                │
  │  502 + receipt      │                     │                │
  │<────────────────────│                     │                │
```

### In-Doubt Settlement (reconciler resolves)

```
Agent                Gateway              Razorpay
  │                     │                     │
  │  (payment request)  │                     │
  │────────────────────>│                     │
  │                     │  create_order       │
  │                     │────────────────────>│
  │                     │  debit → TIMEOUT    │
  │                     │  → SETTLEMENT_UNKNOWN│
  │                     │                     │
  │  202 Retry-After:15 │                     │
  │<────────────────────│                     │
  │                     │                     │
  │  (reconciler sweep) │                     │
  │                     │  find_order(cid)    │
  │                     │────────────────────>│
  │                     │  order_payments     │
  │                     │────────────────────>│
  │                     │  → SETTLED (via rec)│
  │                     │  → fulfil           │
```

## Threat Table

| ID | Threat | Mitigation |
|---|---|---|
| T1 | LLM tricked into overspending | Server-side gate with per-call cap and daily pool, enforced from ledger state |
| T2 | Agent key leak | Resource-hash binding, 300s TTL, single-use jti, daily pool limit |
| T3 | Challenge replay | jti UNIQUE constraint, hash binding prevents cross-resource use |
| T4 | Confused deputy | agentKid in challenge bound to JWS kid; mismatch = 403 |
| T5 | Double payment | CAS with rank monotonicity; jti UNIQUE constraint |
| T6 | Double refund | Read-before-write convergence + Idempotency-Key header |
| T7 | Audit tampering | SHA-256 hash chain + signed checkpoints + append-only trigger |
| T8 | Timeout misread as failure | SETTLEMENT_UNKNOWN state; no exception→FAILED path |
| T9 | Prompt injection (catalog) | Honeypot in enterprise-gpu-node; server gate denies regardless of model |
| T10 | Budget TOCTOU | Policy gate + reservation insert in one BEGIN IMMEDIATE transaction |

## CAS Contract

```python
cas(conn, challenge_id, to_state, *, actor, event, payload, also, attempt_inc, **fields)
→ (result, audit_seq)
# result ∈ {"APPLIED", "STALE", "ILLEGAL", "ORPHAN"}
```

- `APPLIED`: transition succeeded, side-writes executed, audit appended
- `STALE`: target rank already reached or exceeded (no-op)
- `ILLEGAL`: current state not in ALLOWED_FROM set for target
- `ORPHAN`: challenge_id not found

## Hash Chain Formula

```
entry_hash = SHA256(
  prev_hash | challenge_id | event | to_state | to_rank | actor | jcs(payload)
)
```

Joined with literal `|`. `None` rendered as empty string. `prev_hash` of the first row = `"0" * 64`.

## Reservation Lifecycle

| Transition | Side-write |
|---|---|
| → FULFILLED | `budget_reservations.status = 'CAPTURED'` |
| → COMPENSATED | `budget_reservations.status = 'RELEASED'`, `mandates.debited_paise -= amount` |
| → FAILED | `budget_reservations.status = 'RELEASED'` |
| → SETTLED | `mandates.debited_paise += amount` |
| → FULFILLED (day-pass) | `INSERT INTO passes(...)` |
