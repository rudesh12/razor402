# Razor402 — HTTP 402 Payment Protocol on Razorpay Test Rails

> An INR-native HTTP 402 payment protocol that lets an AI agent autonomously purchase API access. Not affiliated with or endorsed by Razorpay.

## Quickstart

```bash
cp .env.example .env
python scripts/keygen.py          # paste output into .env
pip install -e ".[dev]"
python scripts/seed.py

# Terminal 1: Merchant
uvicorn merchant.app:app --port 9000

# Terminal 2: Gateway
uvicorn gateway.app:app --port 8000

# Terminal 3: Demo
python -m agent.buyer --replay --mission rag
```

Or with Docker:
```bash
make up
make demo
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        TRUST BOUNDARY                          │
│                                                                 │
│  ┌──────────┐    402 + JWS     ┌──────────────┐   Razorpay    │
│  │ AI Agent │ ──────────────── │   Gateway    │ ──────────── ║ │
│  │          │   X-PAYMENT      │ (Facilitator)│   test mode  ║ │
│  └──────────┘                  └──────┬───────┘              ║ │
│       │                               │                      ║ │
│  holds keypair              holds credentials                ║ │
│  never credentials          sets price                       ║ │
│  never money                moves money                      ║ │
│                                       │                      ║ │
│                               ┌───────┴───────┐             ║ │
│                               │  BuildBroker  │             ║ │
│                               │  (Merchant)   │             ║ │
│                               └───────────────┘             ║ │
└─────────────────────────────────────────────────────────────────┘

The agent holds a keypair, never credentials, never money.
The facilitator alone moves money and sets price.
```

## Capability Table

| Capability | Status |
|---|---|
| Orders API | Real (test mode) |
| Server-to-server payment creation | Harness (simulated per-call debits) |
| Refunds API | Harness (simulated with convergence) |
| Webhook HMAC verification | Real code, locally signed replay |
| UPI mandate / SBMD block | Simulated; allowance semantics enforced in `mandates` |
| Provisioned resources | Simulated sandbox tokens |

Orders are real test-mode calls; per-call debit mode is latched at startup and recorded in every audit row.

## State Machine

| State | Rank | Can transition from |
|---|---|---|
| ISSUED | 10 | — (row insert) |
| VERIFIED | 20 | ISSUED |
| SETTLING | 25 | VERIFIED |
| SETTLEMENT_UNKNOWN | 28 | SETTLING |
| SETTLED | 30 | SETTLING, SETTLEMENT_UNKNOWN |
| FAILED | 35 | ISSUED, VERIFIED, SETTLING, SETTLEMENT_UNKNOWN |
| FULFILLING | 40 | SETTLED |
| FULFILLED | 50 | FULFILLING |
| COMPENSATING | 60 | SETTLED, FULFILLING |
| COMPENSATED | 70 | COMPENSATING |
| DEAD_LETTER | 75 | SETTLING, SETTLEMENT_UNKNOWN, COMPENSATING, FULFILLING |

**Terminal states:** FAILED, FULFILLED, COMPENSATED, DEAD_LETTER

Three no-op classes: STALE (rank already past target), ILLEGAL (from-set forbids), ORPHAN (row missing).

## FAQ

**Why not an API key with a prepaid balance?**
A key is a bearer credential: whoever holds it spends until the balance dies, with no per-action bound. A Razor402 authorization binds one resource hash, one amount, one agent key, and a 300-second window, and is single-use by `jti`.

**Why 402 rather than a paywall body in a 200?**
Status codes are the machine-readable contract; generic middleware can branch on 402 without parsing bespoke bodies. HTTP 402 is reserved by the HTTP standard; Razor402 defines an INR payment scheme over it.

**Why not x402 with USDC?**
Indian merchants cannot settle in crypto. The buyer-side mechanics are the same; only the rail changes. Wire-inspired by x402; an independent INR implementation.

**What about unit economics?**
Per-call debits are not viable on today's rails — UPI Autopay requires a 24-hour pre-debit notification and cards carry fixed MDR. The production shape is per-call obligations batched into one Razorpay order per agent per interval; compensation before batch settlement costs nothing because no money has moved. Test mode settles per call so the full lifecycle is observable.

**Who issues agent keys, and what if one leaks?**
A registry (the allowlist) today; delisting is revocation. Blast radius is bounded by the resource-hash binding, the TTL, single-use `jti`, and the server-side daily pool.

## What is mocked and why

- **SBMD block** is simulated; allowance semantics are enforced locally in the `mandates` table.
- **BuildBroker** is a demonstration merchant; prices are modeled on real tiers; provisioning is simulated with deterministic sandbox tokens.
- **Payment mode**: the harness adapter generates `pay_H` / `rfnd_H` / `order_H` prefixed IDs so real and simulated payments are distinguishable.

## Tests

```bash
pytest tests/ -q             # all tests
pytest tests/ -q --tb=short  # with short tracebacks
```

**Test manifest:** T01–T60 covering core crypto, state machine, handshake, policy enforcement, idempotency, compensation, webhooks, day pass, injection veto, and honesty checks.

## Future Work

- SBMD mandate lifecycle with real UPI Autopay
- Multi-tenant facilitator with per-merchant configuration
- Postgres + advisory locks for production concurrency
- Queue-backed reconciler (Redis/RabbitMQ)
- Per-agent velocity limits and fraud scoring
- Settlement batching: per-call obligations batched into one Razorpay order per agent per interval
