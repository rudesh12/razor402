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

