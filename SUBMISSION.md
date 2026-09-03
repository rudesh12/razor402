# SUBMISSION

## What it solves

AI agents can now choose tools and APIs autonomously, but most paid APIs still assume a human subscription, a stored API key, or a manual checkout. That leaves merchants unable to sell to a new class of buyer, and it creates a real spending-control problem once an agent acts on its own.

Razor402 makes a merchant endpoint machine-purchasable over HTTP 402. The merchant returns a signed challenge carrying price, resource binding, and expiry. An LLM buyer decides whether the purchase serves its task and writes a rationale that is signed and permanently audit-logged. A deterministic server-side gate — not the model — enforces the per-call cap, daily pool, and merchant allowlist from ledger state. A facilitator holds the Razorpay credentials; the agent never does.

When payment succeeds but the merchant API fails, the system runs a compensation saga: it checks for an existing refund, issues at most one, and returns a machine-readable refund receipt. Every money action lands in a tamper-evident hash-chained audit log.

Flagship use case: an AI coding agent with a ₹150 budget autonomously procuring inference, vector-search, and market-data quotas.

## What broke, and how you got out

*(Assembled from BREAKAGES.md entries during the build)*

### B1 — setuptools build backend path

**Phase:** P0
**Symptom:** `ModuleNotFoundError: No module named 'setuptools.backends'`
**First hypothesis:** Missing dependency
**Why it was wrong:** The `build-backend` path in pyproject.toml was incorrect
**Actual cause:** Used `setuptools.backends._legacy:_Backend` instead of `setuptools.build_meta`
**Fix:** Corrected the build-backend path
**Test added:** Installation now succeeds as part of CI
**Time lost:** 5 minutes

---

## Answers

1. **Project name:** Razor402
2. **One-liner:** HTTP 402 payment protocol for AI agent commerce on Razorpay test rails
3. **Tech stack:** Python 3.11+, FastAPI, SQLite (WAL), Ed25519 JWS, Razorpay SDK
4. **What's real:** Orders API (test mode), HMAC webhook verification, Ed25519 signatures
5. **What's simulated:** Per-call payments (harness adapter), SBMD mandate block, merchant provisioning
6. **Key invariant:** I2 — LLM proposes purchases; a server-side deterministic gate authorizes them. The gate cannot be talked out of a refusal.
7. **Hardest bug:** See BREAKAGES.md
8. **Residual risk:** Dead-lettered transactions require human intervention; simulated SBMD block does not cover real UPI Autopay notification requirements
9. **If I had more time:** Multi-tenant facilitator, Postgres + advisory locks, settlement batching
10. **Lines of code:** ~3000 (estimated)
11. **Time spent:** Build session
12. **Demo command:** `make demo`
