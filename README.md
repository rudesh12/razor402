# Razor402 — Fiat & UPI-Native HTTP 402 Agentic Payment Gateway

> **AI Recommends. Humans Approve. The Server Enforces. Razorpay Settles.**  
> An INR and UPI-native HTTP 402 payment protocol enabling autonomous AI agent commerce on Razorpay test rails.  
> *Not affiliated with or endorsed by Razorpay.*

[![Tests](https://img.shields.io/badge/tests-97%20passed%20%7C%20100%25-brightgreen.svg)](#test-suite)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Protocol](https://img.shields.io/badge/protocol-HTTP%20402%20%2B%20Ed25519%20JWS-indigo.svg)](#protocol-wire-specification)
[![Rails](https://img.shields.io/badge/rails-Razorpay%20Test%20Mode-0052cc.svg)](#capability-matrix)
[![State Machine](https://img.shields.io/badge/state%20machine-11--state%20CAS-orange.svg)](#11-state-cas-machine)
[![Pitch Video](https://img.shields.io/badge/demo-5--min%20pitch%20video-red.svg)](https://youtu.be/hb4UagP_dsM)

---

## 📺 5-Minute Pitch & Live Demo Video

Watch the complete pitch and architecture walkthrough:  
▶️ **[Razor402 — 5-Minute Video Walkthrough](https://youtu.be/hb4UagP_dsM)**

---

## 💡 What Razor402 Solves

Autonomous AI agents can dynamically research, write code, and orchestrate complex tasks, but **they cannot buy anything on their own**.

Merchants face an impasse:
1. **Human Credit Cards in Agent Hands**: Catastrophic prompt-injection and financial leakage risk.
2. **Manual Human Checkouts**: Destroys the speed and autonomy of agentic workflows.
3. **Crypto-Only 402 Protocols (e.g. Coinbase x402)**: Incompatible with domestic INR merchants, RBI regulations, and UPI rails.

**Razor402 bridges this divide.** It transforms API endpoints into machine-purchasable resources using the standard `HTTP 402 Payment Required` status code, backed by Razorpay settlement, deterministic policy guardrails, and cryptographic human sign-off.

---

## 🏛️ The 4-Beat Protocol Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                     TRUST BOUNDARY                                      │
│                                                                                         │
│  ┌─────────────────┐       HTTP 402 Challenge        ┌───────────────────────────────┐  │
│  │ AI Sourcing     │ ◄─────────────────────────────  │       Razor402 Gateway        │  │
│  │ Analyst (Agent) │ ─────────────────────────────►  │  • Zero-I/O Policy Gate       │  │
│  └─────────────────┘    X-PAYMENT (Ed25519 JWS)      │  • Dynamic 402 Pricing Engine │  │
│           │                                          │  • Tamper-Evident SHA Ledger  │  │
│           │ Proposes PO / Rationale                  └───────────────┬───────────────┘  │
│           ▼                                                          │                  │
│  ┌─────────────────┐    BOM SHA-256 + Ceiling Sign-off               │                  │
│  │  Human Approver │ ────────────────────────────────────────────────┤                  │
│  │  (Lead / CFO)   │         (Stored in Append-Only Ledger)          │                  │
│  └─────────────────┘                                                 │                  │
│                                                      ┌───────────────┴───────────────┐  │
│                                                      │       Settlement & rails      │  │
│                                                      │  • Razorpay Orders & Refunds  │  │
│                                                      │  • Upstream Merchant APIs     │  │
│                                                      └───────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1. AI Recommends
The autonomous AI analyst reads the machine-readable vendor catalog (`/.well-known/agent-catalog`), compares competitive options on unit economics (e.g., DeepSeek vs GLM vs Gemini, Weaviate vs Qdrant), and compiles an itemized **Purchase Order (PO)** with transparent alternative derivations.

### 2. Humans Approve
Before any money can move, human leadership (Engineering Lead, Finance Controller, or CTO) reviews the PO in the Human Approval Modal. Approving locks the PO with a **canonical RFC-8785 SHA-256 Bill-of-Materials (BOM) hash** and hard spending ceiling committed directly to the audit ledger.

### 3. The Server Enforces
A **zero-I/O deterministic policy gate** authorizes all transactions against SQLite ledger state. Even if the LLM is prompt-injected or tricked by adversarial inputs, the server gate enforces daily pools and per-call caps, failing closed (`403 POLICY_DENY`).

### 4. Razorpay Settles
Upon authorization, the gateway completes settlement on Razorpay rails, provisioned quotas are delivered upstream, and audit entries are appended to a cryptographic hash chain.

---

## ⚡ Quickstart

### 1. Clone & Set Up Environment

```bash
git clone https://github.com/rudesh12/Razor402.git
cd Razor402

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # On Windows
# source .venv/bin/activate     # On Linux / macOS

# Install package in development mode
pip install -e ".[dev]"
```

### 2. Configure Environment & Keys

```bash
cp .env.example .env
python scripts/keygen.py         # Generate Ed25519 gateway & agent keypairs
# Paste output keys into .env
```

### 3. Initialize & Seed Database

```bash
python scripts/reset_db.py       # Resets & seeds razor402.db with policy mandates
```

### 4. Run Servers

**Terminal 1 — Upstream Merchant (Port 9000):**
```bash
uvicorn merchant.app:app --port 9000 --reload
```

**Terminal 2 — Razor402 Gateway (Port 8000):**
```bash
uvicorn gateway.app:app --port 8000 --reload
```

Open **`http://127.0.0.1:8000`** in your browser to explore the unified interface.

---

## 🖥️ Interactive Web Interface Tour

The unified single-page application (`http://127.0.0.1:8000`) contains 6 integrated operational views:

| View | Anchor | Highlights |
|---|---|---|
| **System View** | `#system` | Live 4-node animated topology (`Agent` ↔ `Gateway` ↔ `Razorpay/Merchant` ↔ `Ledger`) with live telemetry and merchant growth metrics. |
| **Procurement** | `#procurement` | Mission objective selector, dynamic vendor comparison drawer, itemized BOM, and human authorization modal with canonical BOM hash. |
| **Vendor Catalog** | `#catalog` | 41+ discovery items, machine-readable specifications, Standard Razorpay Checkout modal, and autonomous **🤖 Agent Buy · 402** trigger. |
| **Protocol Inspector** | *(Flyout)* | Wire-level frame replay: 402 Challenge, Ed25519 JWS payload breakdown, in-protocol upsell alerts, and 502 compensation receipts. |
| **Spend Cockpit** | `#spend` | Dual-lens analytics: **🏢 Buyer Lens** (Committed spend, daily pools) vs **🏪 Merchant Lens** (AOV growth, upsell take-rate). |
| **Controls** | `#controls` | Live adversarial attack simulator: prompt injection, confused deputy, replay attack, pool drain, and envelope revocation. |
| **Audit Trail** | `#audit` | Merkle-style SHA-256 hash chain with live tamper simulation and mathematical block-by-block verification. |

> **Demo Director**: Press keys <kbd>1</kbd> through <kbd>9</kbd> and <kbd>0</kbd> to sequentially advance through the presentation narrative.

---

## 🔬 Protocol Wire Specification

Razor402 implements standard HTTP semantics over HTTP 402:

### Step 1: Unpaid Request
```http
POST /provision/deepseek-v4-flash HTTP/1.1
Host: 127.0.0.1:8000
X-Razor402-Agent: agt_coding_01
```

### Step 2: HTTP 402 Payment Challenge
```http
HTTP/1.1 402 Payment Required
WWW-Authenticate: Razor402 realm="buildbroker", challenge="ey..."
X-Razor402-Challenge-Id: 01a06e06-0b32-7b9d-a925-706ec9a9dcb4
Content-Type: application/json

{
  "x402Version": 1,
  "error": "PAYMENT_REQUIRED",
  "accepts": [{
    "scheme": "razorpay-inr",
    "network": "razorpay-test",
    "amountPaise": 400,
    "payTo": "acc_buildbroker_test",
    "resource": "/provision/deepseek-v4-flash",
    "resourceHash": "sha256:f70139d6123fce97168bb59bb892364807537d00d5bf0e54db06484fadb97e71",
    "extra": {
      "challengeId": "01a06e06-0b32-7b9d-a925-706ec9a9dcb4",
      "nonce": "tTdihm9YhLUh9SyKeCtC8A",
      "exp": 1788552584
    }
  }],
  "price_options": [
    { "kind": "single", "price_paise": 400, "calls": 1 },
    { "kind": "day_pass", "price_paise": 4000, "calls": 10, "breakEvenCalls": 10 }
  ],
  "challengeJws": "eyJhbGciOiJFZERTQSIsImtpZCI6ImdhdGV3YXki..."
}
```

### Step 3: Paid Request with Signed JWS Authorization
```http
POST /provision/deepseek-v4-flash HTTP/1.1
Host: 127.0.0.1:8000
X-Razor402-Agent: agt_coding_01
X-PAYMENT: eyJhbGciOiJFZERTQSIsImtpZCI6ImFndF9jb2RpbmdfMDEifQ...
```

### Step 4: Settlement & Upstream Fulfilment
```http
HTTP/1.1 200 OK
X-Razor402-State: FULFILLED
X-Payment-Response: {"paymentId": "pay_H0abddf80aa", "status": "captured"}

{
  "item_id": "deepseek-v4-flash",
  "provisioned_resource": {
    "sandbox_api_key": "sb_sk_deepseek_df47cdbc9591",
    "quota": { "tokens": 128000 },
    "endpoint": "https://api.buildbroker.dev/v1/inference/generate"
  }
}
```

---

## 🔄 11-State CAS Machine

Every transaction is governed by an atomic Compare-And-Swap (CAS) state machine:

```
                  ┌─────────┐
                  │ ISSUED  │
                  └────┬────┘
                       ▼
                 ┌───────────┐
                 │ VERIFIED  │
                 └─────┬─────┘
                       ▼
                 ┌───────────┐
                 │ SETTLING  │
                 └─────┬─────┘
         ┌─────────────┴─────────────┐
         ▼                           ▼
┌───────────────────┐        ┌───────────────┐
│SETTLEMENT_UNKNOWN │───────►│    SETTLED    │
└────────┬──────────┘        └───────┬───────┘
         │ (sweeper reconciles)      ▼
         │                     ┌───────────┐
         │                     │ FULFILLING│
         │                     └─────┬─────┘
         │               ┌───────────┴───────────┐
         ▼               ▼                       ▼
    ┌────────┐    ┌───────────┐          ┌──────────────┐
    │ FAILED │    │ FULFILLED │          │ COMPENSATING │
    └────────┘    └───────────┘          └───────┬──────┘
                                                 ▼
                                         ┌──────────────┐
                                         │ COMPENSATED  │
                                         └──────────────┘
```

| State | Rank | Allowed Transitions | Description |
|---|---|---|---|
| `ISSUED` | 10 | Insert | 402 Challenge issued with cryptographically signed parameters |
| `VERIFIED` | 20 | ISSUED | Agent's Ed25519 JWS verified; policy gate passed |
| `SETTLING` | 25 | VERIFIED | Settlement initiated on Razorpay rails |
| `SETTLEMENT_UNKNOWN` | 28 | SETTLING | Network drop / timeout; queued for background sweeper |
| `SETTLED` | 30 | SETTLING, SETTLEMENT_UNKNOWN | Payment successfully captured |
| `FULFILLING` | 40 | SETTLED | Upstream merchant resource provisioning underway |
| `FULFILLED` | 50 | FULFILLING | Credentials successfully provisioned and delivered (200 OK) |
| `COMPENSATING` | 60 | SETTLED, FULFILLING | Merchant delivery failed; initiating autonomous refund saga |
| `COMPENSATED` | 70 | COMPENSATING | Refund issued on Razorpay, budget released, audit recorded |
| `FAILED` | 35 | ISSUED, VERIFIED, SETTLING | Denied by policy gate, signature invalid, or mandate exhausted |
| `DEAD_LETTER` | 75 | Any non-terminal | Permanent anomaly; preserved for manual operator review |

---

## 🛡️ Security & Adversarial Defenses

1. **Deterministic Zero-I/O Server Gate**: Policy rules (per-call limits, daily caps, allowlists) are evaluated strictly against SQLite ledger rows. The model's natural language rationale cannot override mathematical limits.
2. **Canonical RFC-8785 BOM Hashing**: Prevents line-item tampering between human approval and execution. If an agent tries to substitute an approved model for a more expensive one, the execution endpoint rejects it (`409 BOM_MISMATCH`).
3. **Replay Protection with Single-Use JTI**: Every authorization payload embeds a cryptographically unique `jti` (JWT ID). Concurrent requests with the same JTI yield atomic cache hits without secondary debits.
4. **Tamper-Evident Ledger**: The SQLite `audit` table forms a cryptographic SHA-256 hash chain (`prev_hash` → `entry_hash`). Database triggers (`BEFORE UPDATE`, `BEFORE DELETE`) physically reject modifications to historical records.
5. **PO Killswitch**: Revoking a purchase order immediately blocks all subsequent execution attempts at the server boundary with `403 ENVELOPE_REVOKED`.

---

## 🧪 Test Suite

The test suite contains **97 automated tests** covering core cryptography, CAS transitions, idempotent concurrency, adversarial attacks, and compensation sagas:

```bash
# Run all tests
pytest tests/ -q

# Run with verbose reporting
pytest tests/ -v
```

```text
======================= 97 passed in 32.02s =======================
```

### Test Coverage Highlights
- `test_core.py`: Ed25519 signing, RFC-8785 canonical JSON hashing, money arithmetic.
- `test_state_machine.py`: CAS rank transitions, stale no-ops, illegal jumps.
- `test_handshake.py`: Complete HTTP 402 challenge/response roundtrips.
- `test_policy.py`: Server-gate budget limits, allowlists, prompt injection defense.
- `test_idempotency.py`: Concurrent requests, single settlement guarantees, JTI deduplication.
- `test_compensation.py`: Upstream delivery crash, automatic refund generation, budget restoration.
- `test_checkout.py`: Standard Razorpay Web Checkout order creation and HMAC verification.
- `test_demo_api.py`: Protocol Inspector endpoints, live attack simulation, failure injection.
- `test_procurement.py`: Purchase Order creation, BOM canonical hashing, approval state in ledger.
- `test_integration.py`: Webhooks, day-pass activation, honesty assertions, secret leak checks.

---

## 📁 Repository Structure

```text
Razor402/
├── agent/                  # Autonomous buyer client & LLM procurement logic
│   ├── buyer.py            # CLI buyer agent with budget management
│   ├── transport.py        # 402 handshake client & JWS signing
│   └── wallet.py           # Local client wallet & key management
├── core/                   # Core crypto, canonicalization, catalog & errors
│   ├── canonical.py        # RFC-8785 JSON Canonicalization Scheme (JCS)
│   ├── catalog.py          # Vendor catalog, agent policies & spec definitions
│   ├── crypto.py           # Ed25519 JWS signing and verification
│   └── money.py            # Integer paise money representation
├── facilitator/            # Razorpay settlement adapter & compensation refunder
│   ├── rzp.py              # Razorpay SDK adapter (test mode / harness)
│   ├── settler.py          # Settlement state transition handlers
│   └── refunder.py         # Compensation saga & read-before-write refunding
├── gateway/                # FastAPI Gateway application & static SPA
│   ├── app.py              # Main ASGI app & routing
│   ├── console_api.py      # Procurement BOM drafting & human approval APIs
│   ├── demo_api.py         # Interactive Protocol Inspector & attack simulator
│   ├── middleware.py       # Intercepting 402 challenge/payment middleware
│   ├── pricing.py          # Dynamic pricing engine (single vs day-pass upsell)
│   └── static/index.html   # Unified single-page application
├── merchant/               # Upstream mock merchant API
│   └── app.py              # Upstream provider simulation & chaos endpoints
├── policy/                 # Deterministic security guardrails
│   ├── guardrails.py       # Client-side spending advisory checks
│   └── server_gate.py      # Zero-I/O server-side authorization gate
├── reconciler/             # Background sweeper for in-doubt transactions
│   └── sweeper.py          # Asynchronous poller for SETTLEMENT_UNKNOWN
├── scripts/                # Utility scripts & CLI demo drivers
│   ├── keygen.py           # Ed25519 keypair generator
│   ├── probe.py            # Razorpay credential capability probe
│   ├── reset_db.py         # Safe database reset & mandate reseed
│   └── seed.py             # Database seeder
├── state/                  # Database models & tamper-evident ledger
│   ├── db.py               # SQLite WAL connection manager
│   ├── ledger.py           # CAS state transitions & SHA-256 hash chaining
│   └── schema.sql          # Database tables, triggers & indexes
└── tests/                  # 97 pytest test suites
```

---

## ⚖️ Capability Matrix & Engineering Honesty

| Capability | Implementation Status | Notes |
|---|---|---|
| **Orders API** | Real (Razorpay Test Mode) | Live test orders created via Razorpay Python SDK |
| **Webhook HMAC Verification** | Real Code | Verifies SHA-256 HMAC signatures on payment events |
| **Cryptographic Signatures** | Real Code | Ed25519 JWS signing and verification over RFC-8785 canonical JSON |
| **Tamper-Evident Ledger** | Real Code | SQLite WAL mode with SHA-256 hash chaining and `BEFORE` triggers |
| **Server-to-Server Payments** | Test Harness | Generates distinguishable `pay_H` prefixed IDs for safe testing |
| **Refunds API** | Test Harness with Convergence | Read-before-write deduplication; generates `rfnd_H` IDs |
| **UPI Mandate / SBMD** | Simulated Allowance | Enforces allowance semantics locally in `mandates` table |
| **Merchant Provisioning** | Mock Sandbox | Returns deterministic sandbox tokens and endpoint URLs |

---

## 📜 License & Disclaimers

This project was built for the **Razorpay AI Hackathon (Track 01: AI Growth & Agentic Commerce)**.  
*Razor402 is an independent research prototype. Not affiliated with or endorsed by Razorpay.*
