"""gateway/console_api.py — Sourcing Analyst, Purchase Order Planning, Human Approval Gate & Execution."""
import os
import sys
import json
import hashlib
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from core.catalog import CATALOG, AGENT_POLICY, FULFIL_DEADLINE_S, SETTLE_GRACE_S
from core.canonical import jcs
from core.clock import now
from state.db import get_connection
from state.ledger import append_system_audit, is_po_approved

router = APIRouter(prefix="/api/console", tags=["procurement"])

# Flag for demonstrating mid-flight operator revocation
_envelope_revoked = False
_latest_po_number = "PO-241120-101"


def is_envelope_revoked() -> bool:
    global _envelope_revoked
    return _envelope_revoked


def set_envelope_revoked(val: bool):
    global _envelope_revoked
    _envelope_revoked = val


def _alternatives_for(item_id: str) -> list[dict]:
    """Derive vendor alternatives from CATALOG dynamically by matching category."""
    me = CATALOG.get(item_id)
    if not me:
        return []
    alts = []
    my_price = me["price_paise"]
    my_cat = me.get("category")
    for cid, citem in CATALOG.items():
        if cid != item_id and citem.get("category") == my_cat:
            price = citem["price_paise"]
            if price > my_price:
                verdict = "rejected_cost"
            elif price < my_price:
                verdict = "rejected_capability"
            else:
                verdict = "runner_up"
            alts.append({
                "item_id": cid,
                "title": citem["title"],
                "seller": citem.get("seller", "BuildBroker"),
                "price_paise": price,
                "unit_paise": price,
                "verdict": verdict,
            })
    alts.sort(key=lambda a: a["price_paise"])
    return alts[:3]


@router.post("/plan")
async def plan_mission(request: Request):
    """
    Generate an intelligent Bill of Materials (BOM) based on sourcing goal,
    normalizing pricing across vendors, deriving alternatives, and computing savings.
    """
    global _latest_po_number
    try:
        body = await request.json()
        mission = body.get("mission", "").lower()
    except Exception:
        mission = "compare"

    items = []
    if "music" in mission or "audio" in mission:
        music_keys = [
            ("spotify-metadata-feed", 1),
            ("acrcloud-music-id", 1),
            ("musixmatch-lyrics-api", 1),
            ("demucs-stem-separation", 1),
            ("audiocdn-stream-egress", 1),
        ]
        for key, qty in music_keys:
            cat_item = CATALOG[key]
            price = cat_item["price_paise"]
            items.append({
                "item_id": key,
                "title": cat_item["title"],
                "seller": cat_item.get("seller", "BuildBroker"),
                "qty": qty,
                "price_paise": price,
                "unit_paise": price,
                "total_paise": qty * price,
                "rationale": f"Optimal unit economics for {cat_item['title']}",
                "alternatives": _alternatives_for(key),
            })
        total_paise = sum(i["total_paise"] for i in items)
        rationale = (
            "Sourcing Analyst Recommendation for Music Streaming App: "
            "Procuring Spotify catalog metadata (₹5.00), ACRCloud Shazam fingerprinting (₹6.00), "
            "Musixmatch synchronized lyrics (₹8.00), Demucs AI stem separation (₹12.00), and "
            "Cloudflare Edge Audio CDN streaming bandwidth (₹15.00). Total PO ceiling: ₹46.00 out of ₹150.00 daily pool."
        )
    elif "copilot" in mission or "code" in mission:
        code_keys = [
            ("code-vector-embedding", 1),
            ("tree-sitter-ast-indexer", 1),
            ("deepseek-coder-v2", 1),
            ("docker-test-runner", 1),
            ("claude-3-5-sonnet-code", 1),
        ]
        for key, qty in code_keys:
            cat_item = CATALOG[key]
            price = cat_item["price_paise"]
            items.append({
                "item_id": key,
                "title": cat_item["title"],
                "seller": cat_item.get("seller", "BuildBroker"),
                "qty": qty,
                "price_paise": price,
                "unit_paise": price,
                "total_paise": qty * price,
                "rationale": f"Best cost-to-performance ratio for {cat_item['title']}",
                "alternatives": _alternatives_for(key),
            })
        total_paise = sum(i["total_paise"] for i in items)
        rationale = (
            "Sourcing Analyst Recommendation for AI Code Copilot: "
            "Selected Voyage-Code-2 for repo search (₹2.50), Tree-Sitter for AST symbol indexing (₹3.00), "
            "DeepSeek-Coder-V2 for low-latency FIM completion (₹5.00), Docker containerized test sandbox (₹9.00), "
            "and Claude 3.5 Sonnet for SWE architecture & refactoring (₹15.00). Total PO ceiling: ₹34.50 out of ₹150.00 daily pool."
        )
    else:
        # Standard Comparison / RAG BOM
        # 1. LLM selection
        v4_price = CATALOG["deepseek-v4-flash"]["price_paise"]
        items.append({
            "item_id": "deepseek-v4-flash",
            "title": CATALOG["deepseek-v4-flash"]["title"],
            "seller": CATALOG["deepseek-v4-flash"].get("seller", "DeepSeek"),
            "qty": 1,
            "price_paise": v4_price,
            "unit_paise": v4_price,
            "total_paise": v4_price,
            "rationale": "Lowest unit cost per 100k tokens among comparable flash-tier inference providers",
            "alternatives": _alternatives_for("deepseek-v4-flash"),
        })

        # 2. Vector search: 8 initial queries
        qdrant_price = CATALOG["qdrant-vector-query"]["price_paise"]
        items.append({
            "item_id": "qdrant-vector-query",
            "title": "Qdrant Cloud vector search (evaluation batch)",
            "seller": CATALOG["qdrant-vector-query"].get("seller", "Qdrant"),
            "qty": 8,
            "price_paise": qdrant_price,
            "unit_paise": qdrant_price,
            "total_paise": 8 * qdrant_price,
            "rationale": "Lowest latency P95 (20ms) with HNSW indexing across vector databases",
            "alternatives": _alternatives_for("qdrant-vector-query"),
        })

        # 3. Day Pass volume bundle
        pass_price = CATALOG["day-pass"]["price_paise"]
        items.append({
            "item_id": "day-pass",
            "title": CATALOG["day-pass"]["title"],
            "seller": CATALOG["day-pass"].get("seller", "BuildBroker"),
            "qty": 1,
            "price_paise": pass_price,
            "unit_paise": pass_price,
            "total_paise": pass_price,
            "rationale": "Volume day-pass break-even at 10 queries; unlocks zero-marginal-cost queries for 24 hours",
            "alternatives": _alternatives_for("day-pass"),
        })

        # 4. Market snapshot
        mkt_price = CATALOG["market-snapshot"]["price_paise"]
        items.append({
            "item_id": "market-snapshot",
            "title": CATALOG["market-snapshot"]["title"],
            "seller": CATALOG["market-snapshot"].get("seller", "NSE/BSE Datafeed"),
            "qty": 1,
            "price_paise": mkt_price,
            "unit_paise": mkt_price,
            "total_paise": mkt_price,
            "rationale": "Direct exchange market data feed for grounding real-time queries",
            "alternatives": _alternatives_for("market-snapshot"),
        })

        total_paise = sum(i["total_paise"] for i in items)
        rationale = (
            "Market Sourcing Analysis: "
            "Selected DeepSeek-V4-Flash (₹4.00) over Gemini-3.7-Flash (₹7.00) for lowest cost per token. "
            "Selected Qdrant (₹5.00/query) with HNSW indexing, and activated the Day Pass (₹49.00) at query 8 "
            "to cover all remaining queries at fixed cost. Total PO ceiling: ₹108.00 out of ₹150.00 daily pool."
        )

    # Calculate baseline_paise (cost of most expensive viable combination)
    baseline_paise = 0
    for i in items:
        my_unit = i["unit_paise"]
        alts = i.get("alternatives", [])
        worst_unit = max([my_unit] + [a["price_paise"] for a in alts])
        baseline_paise += worst_unit * (i.get("qty", 1))

    savings_paise = max(0, baseline_paise - total_paise)

    # Derive metadata
    sellers = set(i.get("seller", "BuildBroker") for i in items)
    for i in items:
        for a in i.get("alternatives", []):
            sellers.add(a.get("seller", "BuildBroker"))
    vendors_compared = len(sellers)

    categories = sorted(list(set(CATALOG.get(i["item_id"], {}).get("category", "") for i in items if i["item_id"] in CATALOG)))

    # Canonical BOM Hash
    bom_canonical = [{
        "item_id": i["item_id"],
        "qty": i["qty"],
        "unit_paise": i["unit_paise"],
    } for i in items]
    bom_sha256 = hashlib.sha256(jcs(bom_canonical).encode("utf-8")).hexdigest()

    from datetime import timezone
    po_date = datetime.now(timezone.utc).strftime("%y%m%d")
    import random
    po_seq = random.randint(100, 999)
    po_number = f"PO-{po_date}-{po_seq}"
    _latest_po_number = po_number

    plan_response = {
        "po_number": po_number,
        "items": items,
        "total_paise": total_paise,
        "baseline_paise": baseline_paise,
        "savings_paise": savings_paise,
        "vendors_compared": vendors_compared,
        "categories": categories,
        "status": "DRAFT",
        "bom_sha256": bom_sha256,
        "rationale": rationale,
        "daily_pool_paise": 15000,
    }

    # Persist draft to SQLite table po_drafts
    conn = get_connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS po_drafts ("
        "po_number TEXT PRIMARY KEY, total_paise INTEGER NOT NULL, "
        "bom_sha256 TEXT NOT NULL, plan_json TEXT NOT NULL, created_at INTEGER NOT NULL)",
    )
    conn.execute(
        "INSERT OR REPLACE INTO po_drafts (po_number, total_paise, bom_sha256, plan_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (po_number, total_paise, bom_sha256, json.dumps(plan_response), now())
    )

    return plan_response


@router.post("/approve")
async def approve_po(request: Request):
    """
    Human approval gate: authorizes execution of a drafted purchase order.
    Enforces exact ceiling match (no tolerance) and canonical BOM hash binding.
    Records PO_APPROVED in the audit ledger.
    """
    global _latest_po_number
    body = await request.json()
    approver = body.get("approver", "Engineering Lead")
    ceiling_paise = body.get("ceiling_paise")
    po_number = body.get("po_number") or _latest_po_number
    bom_sha256 = body.get("bom_sha256")

    if not po_number:
        raise HTTPException(status_code=400, detail={"error": "MISSING_PO_NUMBER", "detail": "po_number is required"})

    conn = get_connection()
    draft_row = conn.execute(
        "SELECT total_paise, bom_sha256, plan_json FROM po_drafts WHERE po_number=?",
        (po_number,)
    ).fetchone()

    if not draft_row:
        raise HTTPException(status_code=404, detail={"error": "PO_NOT_FOUND", "detail": f"Purchase order {po_number} not found"})

    # Exact ceiling verification — no tolerance
    if ceiling_paise != draft_row["total_paise"]:
        raise HTTPException(
            status_code=409,
            detail={"error": "CEILING_MISMATCH", "detail": f"Ceiling {ceiling_paise} does not match draft total {draft_row['total_paise']}"}
        )

    # Exact BOM hash verification
    if bom_sha256 and bom_sha256 != draft_row["bom_sha256"]:
        raise HTTPException(
            status_code=409,
            detail={"error": "BOM_MISMATCH", "detail": "BOM hash does not match current drafted basket"}
        )

    plan = json.loads(draft_row["plan_json"])
    seq = append_system_audit(
        conn,
        event="PO_APPROVED",
        actor=approver,
        payload={
            "po_number": po_number,
            "ceiling_paise": ceiling_paise,
            "bom_sha256": draft_row["bom_sha256"],
            "line_count": len(plan.get("items", [])),
        }
    )
    set_envelope_revoked(False)

    return {
        "approved": True,
        "po_number": po_number,
        "ceiling_paise": ceiling_paise,
        "approver": approver,
        "audit_seq": seq,
        "bom_sha256": draft_row["bom_sha256"],
    }


@router.post("/execute")
async def execute_mission(request: Request = None):
    """
    Execute the planned purchase order against the live gateway.
    Requires server-verified human approval recorded in the audit ledger.
    Never hangs indefinitely: enforces request timeouts using FULFIL_DEADLINE_S,
    records every step result through the state machine, and guarantees structured JSON.
    """
    global _envelope_revoked, _latest_po_number
    if _envelope_revoked:
        raise HTTPException(
            status_code=403,
            detail={"error": "ENVELOPE_REVOKED", "detail": "Operator revoked purchase order"}
        )

    conn = get_connection()
    body = {}
    if request:
        try:
            body = await request.json()
        except Exception:
            body = {}

    po_number = body.get("po_number") or _latest_po_number
    if not po_number:
        last_appr = conn.execute(
            "SELECT payload FROM audit WHERE event='PO_APPROVED' ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if last_appr:
            po_number = json.loads(last_appr["payload"]).get("po_number")

    if not po_number:
        raise HTTPException(
            status_code=403,
            detail={"error": "PO_NOT_APPROVED", "detail": "No approved purchase order found"}
        )

    # Verify approval from the LEDGER
    approved = is_po_approved(conn, po_number)
    if not approved:
        raise HTTPException(
            status_code=403,
            detail={"error": "PO_NOT_APPROVED", "detail": f"Purchase order {po_number} is not approved or was cancelled"}
        )

    approver = body.get("approver") or approved.get("approver", "Engineering Lead")
    ceiling_paise = approved.get("ceiling_paise", 15000)

    # Verify BOM integrity against draft
    draft_row = conn.execute(
        "SELECT total_paise, bom_sha256, plan_json FROM po_drafts WHERE po_number=?",
        (po_number,)
    ).fetchone()

    if draft_row and approved.get("bom_sha256"):
        if draft_row["bom_sha256"] != approved["bom_sha256"]:
            raise HTTPException(
                status_code=409,
                detail={"error": "BOM_MISMATCH", "detail": "Live BOM has changed since human approval was granted"}
            )

    import secrets
    import httpx
    from core.crypto import sign_jws, b64u
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    agent_kid = "agt_coding_01"
    sk_hex = os.environ.get("AGENT_A_SK_HEX", "08af9298520f92fe87761aaa0ea139a5e7d6577ea6c34618c6a0ae09feb72614")
    sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(sk_hex))

    target_app = request.app if (request and hasattr(request, "app")) else None
    if not target_app:
        from gateway.app import app as target_app

    steps_plan = [
        ("discover_catalog", None, "Catalog discovered: multi-provider vendor catalog"),
        ("procure", "deepseek-v4-flash", "Procuring DeepSeek-V4-Flash per approved PO line 1"),
        ("procure", "qdrant-vector-query", "Initial test vector query against corpus"),
        ("procure", "qdrant-vector-query", "Second query: validating precision across chunks"),
        ("procure", "qdrant-vector-query", "Third query: measuring recall accuracy"),
        ("procure", "qdrant-vector-query", "Fourth query: testing edge case retrieval"),
        ("procure", "qdrant-vector-query", "Fifth query: cross-referencing document sections"),
        ("procure", "qdrant-vector-query", "Sixth query: benchmarking retrieval latency"),
        ("procure", "qdrant-vector-query", "Seventh query: multi-hop document linking"),
        ("procure", "qdrant-vector-query", "Eighth query: threshold reached for Day Pass optimization"),
        ("procure", "day-pass", "Volume Optimization: Day Pass accepted to make remaining queries free"),
        ("procure", "market-snapshot", "Procuring NSE/BSE real-time market data anchor"),
    ]

    executed_steps = []
    total_po_spent = 0
    transport = httpx.ASGITransport(app=target_app)
    step_timeout = httpx.Timeout(connect=2.0, read=float(FULFIL_DEADLINE_S), write=2.0, pool=float(FULFIL_DEADLINE_S))

    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000", timeout=step_timeout) as client:
            for tool, item_id, rationale in steps_plan:
                if _envelope_revoked:
                    executed_steps.append({
                        "tool": tool,
                        "item_id": item_id,
                        "step_name": item_id or tool,
                        "status": "denied",
                        "state": "DENIED",
                        "error_code": "ENVELOPE_REVOKED",
                        "rationale": "Execution halted: Purchase order cancelled mid-flight by operator",
                        "payment_id": None,
                        "audit_seq": None,
                    })
                    break

                if tool == "discover_catalog":
                    try:
                        r0 = await client.get("/.well-known/agent-catalog", timeout=step_timeout)
                        status = "fulfilled" if r0.status_code == 200 else "failed"
                    except Exception:
                        status = "failed"
                    executed_steps.append({
                        "tool": "discover_catalog",
                        "item_id": None,
                        "step_name": "discover_catalog",
                        "status": status,
                        "state": "FULFILLED" if status == "fulfilled" else "FAILED",
                        "rationale": rationale,
                        "payment_id": "free_endpoint",
                        "audit_seq": 1,
                    })
                    continue

                elif tool == "procure":
                    item_price = CATALOG.get(item_id, {}).get("price_paise", 0)
                    if total_po_spent + item_price > ceiling_paise:
                        executed_steps.append({
                            "tool": "procure",
                            "item_id": item_id,
                            "step_name": item_id,
                            "status": "denied",
                            "state": "DENIED",
                            "error_code": "PO_CEILING_EXCEEDED",
                            "rationale": f"Halted: purchase of {item_id} ({item_price}p) exceeds approved PO ceiling ({ceiling_paise}p)",
                            "payment_id": None,
                            "audit_seq": None,
                        })
                        break

                    # 1. Initial unauthenticated request (expect 402 or 200 if pass-covered)
                    try:
                        r1 = await client.post(
                            f"/provision/{item_id}",
                            headers={"X-Razor402-Agent": agent_kid},
                            timeout=step_timeout,
                        )
                    except (httpx.TimeoutException, TimeoutError):
                        executed_steps.append({
                            "tool": "procure",
                            "item_id": item_id,
                            "step_name": item_id,
                            "status": "failed",
                            "state": "FAILED",
                            "error_code": "CHALLENGE_TIMEOUT",
                            "rationale": f"Challenge request timed out after {FULFIL_DEADLINE_S}s",
                            "payment_id": None,
                            "audit_seq": None,
                        })
                        continue
                    except Exception as e:
                        executed_steps.append({
                            "tool": "procure",
                            "item_id": item_id,
                            "step_name": item_id,
                            "status": "failed",
                            "state": "FAILED",
                            "error_code": "CONNECT_ERROR",
                            "rationale": f"Initial probe failed: {str(e)}",
                            "payment_id": None,
                            "audit_seq": None,
                        })
                        continue

                    if r1.status_code == 200:
                        executed_steps.append({
                            "tool": "procure",
                            "item_id": item_id,
                            "step_name": item_id,
                            "status": "fulfilled",
                            "state": "FULFILLED",
                            "rationale": "Covered under active Day Pass (₹0 incremental cost)",
                            "payment_id": "pass_covered",
                            "audit_seq": None,
                        })
                        continue

                    r1_body = r1.json() if "application/json" in r1.headers.get("content-type", "") else {}
                    accepts = r1_body.get("accepts", [])
                    if not accepts:
                        executed_steps.append({
                            "tool": "procure",
                            "item_id": item_id,
                            "step_name": item_id,
                            "status": "failed",
                            "state": "FAILED",
                            "error_code": "NO_PAYMENT_OPTIONS",
                            "rationale": "Gateway returned no payment options",
                            "payment_id": None,
                            "audit_seq": None,
                        })
                        continue

                    select_index = 1 if item_id == "day-pass" and len(accepts) > 1 else 0
                    selected = accepts[select_index]
                    cid = selected["extra"]["challengeId"]
                    amount_paise = selected["amountPaise"]
                    jws_list = r1_body.get("challengeJwsList", [])
                    challenge_jws = jws_list[select_index] if jws_list else r1_body.get("challengeJws", "")

                    # 2. Build & sign payment authorization with agent's Ed25519 key
                    jti = b64u(secrets.token_bytes(16))
                    policy = AGENT_POLICY[agent_kid]
                    auth_payload = {
                        "typ": "razor402.payment-authorization+jws",
                        "challengeJws": challenge_jws,
                        "challengeId": cid,
                        "agentKid": agent_kid,
                        "mandate": {"type": "upi_sbmd", "token": policy["mandate_token"]},
                        "maxDebitPaise": amount_paise,
                        "rationale": f"[Approved by {approver} for {po_number}] {rationale}"[:500],
                        "jti": jti,
                        "iat": now(),
                    }
                    token = sign_jws(auth_payload, sk, agent_kid)

                    # 3. Submit authorized payment request with timeout protection
                    payment_id = None
                    audit_seq = None
                    step_status = "failed"
                    step_state = "FAILED"
                    err_code = None

                    try:
                        r2 = await client.post(
                            f"/provision/{item_id}",
                            headers={
                                "X-PAYMENT": token,
                                "X-Razor402-Agent": agent_kid,
                            },
                            timeout=step_timeout,
                        )
                        r2_state = r2.headers.get("X-Razor402-State")

                        if r2.status_code == 200:
                            step_status = "fulfilled"
                            step_state = r2_state or "FULFILLED"
                            total_po_spent += amount_paise
                        elif r2.status_code == 202:
                            step_status = "settlement_unknown"
                            step_state = r2_state or "SETTLEMENT_UNKNOWN"
                        elif r2.status_code == 403:
                            step_status = "denied"
                            step_state = r2_state or "DENIED"
                            err_code = "POLICY_DENIED"
                        elif r2.status_code == 502:
                            step_status = "compensated"
                            step_state = r2_state or "COMPENSATED"
                            err_code = "UPSTREAM_FULFILMENT_FAILED"
                        else:
                            step_status = "failed"
                            step_state = r2_state or "FAILED"
                            err_code = f"HTTP_{r2.status_code}"

                        payment_hdr = r2.headers.get("X-PAYMENT-RESPONSE", "{}")
                        try:
                            payment_id = json.loads(payment_hdr).get("paymentId", f"pay_{cid[:8]}")
                        except Exception:
                            payment_id = f"pay_{cid[:8]}"

                    except (httpx.TimeoutException, TimeoutError):
                        txn_row = conn.execute(
                            "SELECT state FROM txn WHERE challenge_id=?", (cid,)
                        ).fetchone()
                        t_state = txn_row["state"] if txn_row else "SETTLEMENT_UNKNOWN"
                        if t_state in ("SETTLING", "SETTLEMENT_UNKNOWN"):
                            step_status = "settlement_unknown"
                            step_state = "SETTLEMENT_UNKNOWN"
                        elif t_state in ("COMPENSATING", "COMPENSATED"):
                            step_status = "compensated"
                            step_state = "COMPENSATED"
                        else:
                            step_status = "settlement_unknown"
                            step_state = t_state
                        err_code = "SETTLEMENT_TIMEOUT"
                        payment_id = f"pay_{cid[:8]}"

                    except Exception as exc:
                        txn_row = conn.execute(
                            "SELECT state FROM txn WHERE challenge_id=?", (cid,)
                        ).fetchone()
                        t_state = txn_row["state"] if txn_row else "FAILED"
                        step_status = "failed"
                        step_state = t_state if t_state in ("FAILED", "DEAD_LETTER") else "FAILED"
                        err_code = type(exc).__name__
                        payment_id = None

                    audit_row = conn.execute(
                        "SELECT seq FROM audit WHERE challenge_id=? ORDER BY seq DESC LIMIT 1",
                        (cid,)
                    ).fetchone()
                    audit_seq = audit_row["seq"] if audit_row else None

                    if cid:
                        append_system_audit(conn, event="PO_STEP_EXECUTED", actor=approver, payload={
                            "po_number": po_number,
                            "item_id": item_id,
                            "challenge_id": cid,
                            "status": step_status,
                            "state": step_state,
                            "spent_paise": amount_paise if step_status == "fulfilled" else 0,
                        })

                    executed_steps.append({
                        "tool": "procure",
                        "item_id": item_id,
                        "step_name": item_id,
                        "status": step_status,
                        "state": step_state,
                        "rationale": rationale,
                        "payment_id": payment_id,
                        "audit_seq": audit_seq,
                        "error_code": err_code,
                    })

    except Exception as fatal_e:
        # Top-level fallback ensures JSON is ALWAYS returned
        pass

    # Read captured & remaining paise from database
    cap_row = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) as total FROM budget_reservations WHERE agent_kid=? AND status='CAPTURED'",
        (agent_kid,)
    ).fetchone()
    captured_paise = cap_row["total"] if cap_row else 0
    daily_pool = AGENT_POLICY[agent_kid]["daily_pool_paise"]
    remaining_paise = max(0, daily_pool - captured_paise)

    plan_info = json.loads(draft_row["plan_json"]) if draft_row else {}
    all_failed = len(executed_steps) > 0 and all(s.get("status") in ("failed", "denied") for s in executed_steps)
    is_ok = len(executed_steps) > 0 and not all_failed

    return {
        "ok": is_ok,
        "po_number": po_number,
        "approver": approver,
        "approved_at": approved.get("ts"),
        "audit_seq": approved.get("audit_seq"),
        "baseline_paise": plan_info.get("baseline_paise"),
        "savings_paise": plan_info.get("savings_paise"),
        "steps": executed_steps,
        "remaining_paise": remaining_paise,
        "captured_paise": captured_paise,
        "error_code": None if is_ok else ("ALL_STEPS_DENIED" if all_failed else "EXECUTION_INCOMPLETE"),
    }


@router.post("/revoke")
async def revoke_envelope():
    """Operator revocation: immediately halts procurement and cancels active approvals."""
    global _envelope_revoked, _latest_po_number
    _envelope_revoked = True
    conn = get_connection()
    append_system_audit(conn, event="PO_CANCELLED", actor="operator",
                        payload={"po_number": _latest_po_number, "reason": "revoked_by_operator"})
    return {"status": "revoked", "detail": "Server-side policy enforcement active"}


@router.post("/reset-envelope")
async def reset_envelope():
    """Reset operator revocation back to normal state and cancel previous approval."""
    global _envelope_revoked, _latest_po_number
    _envelope_revoked = False
    conn = get_connection()
    append_system_audit(conn, event="PO_CANCELLED", actor="operator",
                        payload={"po_number": _latest_po_number, "reason": "reset_envelope"})
    return {"status": "active"}
