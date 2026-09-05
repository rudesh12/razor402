---
title: Razor402 Final Hackathon Submission Details
tags: [razorpay, hackathon, submission, razor402, agentic-commerce]
date: 2026-09-05
project: Razor402
track: Track 01 - AI Growth & Agentic Commerce
---

# Razor402 — Official Final Submission Entry

---

### Project Name / Title
```text
Razor402: Fiat & UPI-Native HTTP 402 Agentic Payment Gateway
```

---

### Project Objectives
**What does it solve?**

```text
Autonomous AI agents can dynamically research, write code, and orchestrate complex tasks, but they cannot purchase APIs, compute, or data without either human credit cards (a severe prompt-injection and financial risk) or manual human checkouts (which breaks autonomous execution). Furthermore, existing HTTP 402 implementations (e.g., Coinbase x402) rely entirely on crypto and stablecoins, excluding mainstream fiat and UPI rails.

Razor402 bridges this divide by implementing an RFC-compliant HTTP 402 payment gateway on Razorpay test rails:

1. Machine-Readable Commerce: Provides a discovery standard (/.well-known/agent-catalog) where autonomous agents query API pricing, quotas, and in-protocol volume discounts (e.g., single-call vs. day-pass) without web scraping.
2. Deterministic Mathematical Guardrails: Completely decouples LLM reasoning from financial authorization. A zero-I/O server-side policy engine enforces per-call spending caps, daily agent budget pools, and merchant allowlists. The AI can propose purchases, but deterministic math authorizes them.
3. Cryptographic Governance & Audit: Agents compile Purchase Orders (POs) locked by canonical SHA-256 Bill-of-Materials hashes requiring human consent. All transactions, policy verdicts, and refunds are committed to an append-only, SHA-256 hash-chained audit ledger protected by database-level triggers.
4. Zero Money Leakage: Features an 11-state deterministic state machine with automated compensation sagas (instant auto-refund on upstream merchant crash) and idempotent JTI deduplication to eliminate double-spending.
```

---

### GitHub Repository URL
```text
https://github.com/rudesh12/Razor402
```

---

### 5-min Pitch Video Link
```text
https://youtu.be/hb4UagP_dsM
```

---

### Build Challenges & Technical Obstacles
**What issues did you face while building, and how did you solve them?**

```text
1. Concurrency Races & Reentrancy on Parallel Tool Calls (Double-Spend Risk):
• Issue: When parallel agent threads or duplicate tool calls fired simultaneous requests with the same JTI token, uncommitted database rows led secondary threads to evaluate transactions as non-existent and fall through to re-execution.
• Solution: Implemented an atomic Compare-And-Swap (CAS) state machine over SQLite WAL mode. We hardened the replay resolver to detect in-flight states and immediately return 409 IN_FLIGHT, ensuring that across N concurrent requests, exactly one proceeds while replicas await and receive the identical cached receipt.

2. Event Loop Deadlocks in Loopback Autonomous Execution:
• Issue: The interactive Mission Console executed multi-turn agent procurement via synchronous HTTP calls back into the same server. Under single-worker Uvicorn, running synchronous I/O inside an async route blocked the main asyncio event loop from handling the incoming loopback requests it was waiting on (causing httpx.ReadTimeout).
• Solution: Re-architected mission execution endpoints into synchronous route workers dispatched across AnyIO thread pools (anyio.to_thread.run_sync), keeping the primary event loop completely non-blocking.

3. Indeterminate Payment States & Upstream Merchant Crashes (Money Leakage):
• Issue: Real-world network drops during payment gateway settlement leave transactions in an unknown state (SETTLEMENT_UNKNOWN). Furthermore, if an upstream merchant server crashes after payment is captured, the agent loses budget without receiving provisioned credentials.
• Solution: Designed an 11-state deterministic state machine paired with a 15-second background reconciliation sweeper to asynchronously resolve pending gateway orders. Built an automated compensation saga: upon upstream delivery failure, the system transitions to COMPENSATING, invokes Razorpay’s refund API, releases the held budget back to the agent, and logs a tamper-evident audit record.

4. Tamper-Evident Ledger Integrity without Blockchain Overhead:
• Issue: Needed cryptographically verifiable audit trails that could prevent insider database tampering or unauthorized historical modification without high-latency distributed consensus.
• Solution: Constructed a SHA-256 cryptographic hash-chain where each audit row embeds the hash of the preceding entry. SQLite database-level BEFORE UPDATE and BEFORE DELETE triggers prevent modification or pruning. An automated chain-walk verification routine validates every block from genesis to detect and isolate any altered byte.
```

---

### Final Submission Confirmation
```text
[x] I confirm that this is my official final project submission. I understand that no further changes or edits can be made after submitting.
```
