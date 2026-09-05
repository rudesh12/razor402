# DECISIONS

Choices made when spec was ambiguous, recorded during the build.

## D1 — Payment Mode (probed 2026-09-03)

Mode: `MODE_C` (harness) — building without live Razorpay keys configured.
All payments simulated with harness adapter. IDs prefixed `pay_H` / `rfnd_H` / `order_H`.
Orders are real test-mode calls; per-call debit mode is latched at startup and recorded in every audit row.

## D2 — Build Backend (P0)

`pyproject.toml` uses `setuptools.build_meta` as the build backend. The spec did not specify
a build system; chose setuptools as the simplest option compatible with the dependency list.

## D3 — Docker Compose (P0)

Added a `Dockerfile` (not in spec tree but required by `docker-compose.yml`). Simplest
Python 3.11-slim image with pip install.

## D4 — Test Runner Compatibility (P1)

`pytest-asyncio>=0.23` specified in spec, but latest available is 1.4.0 with `asyncio_mode = "auto"`.
Using what pip resolves. Tests run synchronously where possible to avoid async complexity.

## D5 — Makefile Windows Compatibility (P0)

Makefile targets adapted for cross-platform (Windows PowerShell + Unix). `reset-db` uses
`del /f /q` with fallback to `rm -f`. Demo scripts have `.py` fallbacks since `bash` may
not be available on Windows.

## D6 — T26 Pool Exhaustion Test (P3)

In `tests/test_policy.py`, seed pre-existing captured budget reservations up to the daily pool (5000 paise) to cleanly assert that `authorize` denies immediately with 403 `DAILY_POOL_EXHAUSTED`.

## D7 — Razorpay Standard Web Checkout Integration

Integrated Razorpay Standard Web Checkout alongside the autonomous agent 402 protocol:
- Backend order creation: `POST /api/create-order`
- Backend payment verification: `POST /api/verify-payment` (HMAC-SHA256)
- Frontend checkout interface: `GET /checkout` serving `static/checkout.html` with Razorpay modal
- Config endpoint: `GET /api/checkout-config` exposing public key only

## D8 — Dual Environment Variable Support

Supported both `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` and `RZP_KEY_ID` / `RZP_KEY_SECRET` across all modules (`facilitator/rzp.py`, `gateway/checkout.py`, `gateway/app.py`).

## D9 — LLM Provider: Gemini Exclusively

Configured `agent/llm.py` to use `google-genai` with `gemini-2.5-flash`, skipping Anthropic as requested. Provided `GEMINI_API_KEY` in `.env`.

## D1 — Payment Mode (probed 2026-09-03T06:09:27.232891)

Mode: `MODE_C` — network/auth error: `'charmap' codec can't encode character '\u2713' in position 13: character maps to <undefined>`

## D1 — Payment Mode (probed 2026-09-03T06:09:44.761217)

Mode: `MODE_C` (harness) — orders are real, s2s payments unavailable.
Error: `The requested URL was not found on the server.`
Order creation works (tested: `order_TXMxNx7A10MvDK`).

## D10 — Multi-Provider Comparison Shopping Catalog

Expanded `core/catalog.py` with competing market offerings under BuildBroker:
- LLM Inference: DeepSeek-V4-Flash (₹4.00), DeepSeek-V3 (₹5.00), GLM-5.3-Flash (₹5.00), Gemini-3.7-Flash (₹7.00)
- Vector Search: Weaviate (₹3.00), Qdrant (₹5.00), Pinecone (₹8.00)
- Cloud Compute: GCP e2-small (₹20.00), Azure B2s (₹22.00), AWS t3.micro (₹25.00)
- System prompt instructs agent to compare providers on price/specs and record rationale.

## D11 — Mission Console & Human-in-the-Loop Operator Gate

Implemented split-pane UI (`GET /console`) and API (`/api/console/*`):
- Goal definition & solutions architect planner
- Real-time Bill of Materials (BOM) with cost analysis
- Human approval button to fund envelope (₹108.00)
- Live streaming execution showing HTTP 402, settlement, fulfillment, and audit link
- Mid-flight operator revocation button triggering deterministic server-side gate denial (`403 ENVELOPE_REVOKED`).

MODE_B alternative: save a Checkout-created `pay_` id to `agent/fixtures/real_payment.json`.

## D12 — Unified Frontend SPA & Dynamic AI Budget Controller

Consolidated the presentation layer into a self-contained Single Page Application (`gateway/static/index.html`) served directly by FastAPI:
- **Zero external build dependencies**: Runs immediately under `uvicorn gateway.app:app` without requiring Node.js, separate development servers, or CORS.
- **Dynamic AI Agent Budget Tuning**: Dual sliders + number controls for Daily Pool (₹10–₹500) and Per-Call Cap (₹1–₹100) communicating via `POST /api/v1/budget/adjust`, enabling real-time demonstration of deterministic spending gate enforcement.
- **5-View Navigation**: Overview dashboard, 40-resource API Marketplace with Razorpay Standard Checkout modal, Mission Console & BOM planner, Cryptographic Audit Trail with tamper demo, and Operator Settings with chaos injection.

## D13 — Protocol Inspector, Attack Simulator & Demonstrable 402 Wire Suite

Integrated wire-level protocol visualization and automated adversarial test suite directly into the frontend and backend:
- **Protocol Inspector Drawer**: Real-time slide-in wire panel displaying chronological HTTP exchange frames (`req` -> `402 Challenge` -> `req + X-PAYMENT` -> `200 Delivery`) with staged 380ms replay and interactive JWS token inspection.
- **Dual Buy Paths**: Every marketplace card splits into `🤖 Agent Buy · 402` (autonomous cryptographic handshake) and `💳 Human` (standard Razorpay modal), highlighting the core architectural differentiator.
- **Automated Adversarial Scorecard**: 5-attack simulation matrix (`prompt_injection`, `confused_deputy`, `replay`, `pool_drain`, `revoked_envelope`) executing against the live gateway with verifiable `DEFENDED ✓` verdicts.
- **Tamper-to-Verify Narrative Fix**: Removed premature UI mutation on tampering; chain walk animates row-by-row with dynamic border coloring to locate the exact corrupted entry.
- **Demo Director Bar**: Persistent 8-step presentation controller with keyboard shortcuts `1`–`8` for rehearsed, zero-fumble video recording.

## D14 — AI Procurement Analyst Repositioning & System Hero Architecture

Repositioned the core user story from "Autonomous AI Spending Money" to an "AI Sourcing & Procurement Analyst with Server-Enforced Human Sign-off and Merchant Revenue Growth":
- **System Hero View (`#view-system`)**: Interactive 4-node architectural topology (AI Buyer -> Security Boundary -> Razorpay/Merchant -> Audit Ledger) featuring animated transaction flow lines, live metric badges, and dual argument panels: "Why the Merchant Wins" (zero-CAC demand, AOV lift) and "Why Finance Signs Off" (deterministic math, prompt injection immunity).
- **Procurement Vocabulary Alignment**: Replaced tech/robot jargon with enterprise procurement vocabulary: Procurement (Console), Vendor Catalog (Marketplace), Spend (Overview), Controls (Security), Purchase Order Draft (Envelope), and Cancel PO (Revoke).
- **12-Step Demo Director**: Extended the keyboard-driven rehearsal director (`1` through `12`) beginning at System topology and agent-catalog discovery, proceeding through market research, comparison, approval, execution, wire inspection, attack defense, breach simulation, and failure recovery.

## D15 — Ledger-Bound Human Approval Gate & Canonical BOM Hash Enforcement

Implemented formal human sign-off as an authoritative server control rather than client-side UI theatre:
- **Ledger as the Single Source of Truth**: Approval state is recorded directly into the append-only SHA-256 audit chain (`PO_APPROVED`). `is_po_approved()` queries the audit table and verifies no subsequent `PO_CANCELLED` event supersedes it.
- **Canonical BOM Hash (`bom_sha256`)**: Draft purchase orders generate a canonical SHA-256 digest over sorted `{item_id, qty, unit_paise}` using RFC-8785 JSON Canonicalization Scheme (JCS). `POST /api/console/approve` and `POST /api/console/execute` reject any altered basket with `409 BOM_MISMATCH`.
- **Exact Ceiling Enforcement**: `POST /api/console/approve` strictly enforces `ceiling_paise == draft_total` (no tolerance window), rejecting discrepancies with `409 CEILING_MISMATCH`. The approved ceiling is enforced as a third independent limit alongside daily pool and per-call cap during execution.
- **System-Row Hash Parity**: System-scoped events without challenge IDs (`PO_APPROVED`, `PO_CANCELLED`, `UPSELL_OFFERED`) utilize standard `note()` appending, preserving SHA-256 chain integrity and 100% `verify_chain()` validation.

## D16 — In-Protocol Upsell & Merchant-Side Economics Telemetry

Solved the buyer/merchant narrative tension by demonstrating that machine-to-machine commerce inherently drives merchant average order value (AOV):
- **402 Challenge Upsell Surface**: `gateway/pricing.py` and `_mint_challenge` inject `price_options` containing single-call and volume day-pass options. The agent chooses based on unit economics (e.g. ₹4 single call vs ₹40 day pass = 10x order value lift at zero customer acquisition cost).
- **Live In-Protocol Upsell Visualizer**: The Protocol Inspector detects multiple options on the wire and renders a `💹 UPSELL OFFERED IN-PROTOCOL` badge.
- **Dual-Lens Spend View**: Interactive toggle on `#view-spend` switching between Buyer View (committed spend, savings, policy denials, active subscriptions) and Merchant View (revenue captured, AOV lift, upsell take-rate, zero-CAC orders).
- **Audit-Grounded Metrics**: Zero fabricated baseline numbers. `upsell_offered`, `upsell_accepted`, `aov_single_paise`, and `aov_pass_paise` are computed directly from ledger events and transaction history.

