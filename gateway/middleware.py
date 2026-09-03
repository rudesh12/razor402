"""gateway/middleware.py — 402 intercept + mint challenge."""
import json
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from core.ids import uuid7
from core.clock import now
from core.crypto import sign_jws, b64u
from core.canonical import resource_hash, jcs
from core.catalog import (
    CATALOG, MERCHANT_ACCOUNT, POLICY_VERSION,
    CHALLENGE_TTL_S, PRICE_BASIS_UNIT,
)
from core.errors import Razor402Error, ERROR_STATUS
from state.db import get_connection
from state.states import RANK
from state.ledger import cas, note
from gateway.verification import verify_proof, VerifiedProof
from gateway.replay import resolve as replay_resolve
from gateway.pricing import check_pass, build_accepts
from policy.server_gate import authorize
from facilitator.settler import settle
from gateway.fulfilment import fulfil


def get_gateway_keys():
    """Load gateway signing keys from environment."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    gw_sk_hex = os.environ.get("GW_SK_HEX", "")
    agent_a_hex = os.environ.get("AGENT_A_SK_HEX", "")
    agent_b_hex = os.environ.get("AGENT_B_SK_HEX", "")

    keys = {}
    pubs = {}

    if gw_sk_hex:
        sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(gw_sk_hex))
        keys["gateway"] = sk
        pubs["gateway"] = sk.public_key()

    if agent_a_hex:
        sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(agent_a_hex))
        keys["agt_coding_01"] = sk
        pubs["agt_coding_01"] = sk.public_key()

    if agent_b_hex:
        sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(agent_b_hex))
        keys["agt_coding_02"] = sk
        pubs["agt_coding_02"] = sk.public_key()

    return keys, pubs


async def intercept_provision(request: Request, adapter, call_next=None):
    """
    Main 402 intercept middleware for /provision/* paths.
    Flow:
    1. Read body
    2. Parse item from path
    3. If no X-PAYMENT: check pass → mint challenge → 402
    4. If X-PAYMENT: verify → replay → gate → settle → fulfil
    """
    conn = get_connection()
    keys, pubs = get_gateway_keys()
    now_ts = now()

    # Read raw body
    body = await request.body()
    path = request.url.path
    method = request.method
    query = str(request.url.query) if request.url.query else ""

    # Extract item_id from path
    parts = path.strip("/").split("/")
    if len(parts) < 2:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    item_id = parts[1]  # /provision/{item_id}

    if item_id not in CATALOG:
        return JSONResponse(status_code=404,
                            content={"error": f"Unknown item: {item_id}"})

    item = CATALOG[item_id]
    payment_header = request.headers.get("X-PAYMENT", "")

    if not payment_header:
        # === NO PAYMENT: check pass or mint challenge ===

        # Check for active pass
        kid = request.headers.get("X-Razor402-Agent", "agt_coding_01")
        active_pass = check_pass(conn, kid, item_id, now_ts)
        if active_pass:
            note(conn, None, "PASS_CALL", kid,
                 {"charge_paise": 0, "pass_ref": active_pass["challenge_id"],
                  "item_id": item_id})
            # Forward to upstream free
            return await _forward_free(request, item_id, active_pass)

        # Mint challenge(s)
        return _mint_challenge(conn, keys, pubs, kid, item_id, item,
                               method, path, query, body, now_ts)

    # === HAS PAYMENT: verify → replay → gate → settle → fulfil ===
    try:
        proof = verify_proof(payment_header, method, path, query, body,
                             {"gateway": pubs["gateway"]} if "gateway" in pubs else {},
                             {k: v for k, v in pubs.items() if k != "gateway"},
                             now_ts)
    except ValueError as e:
        error_msg = str(e)
        code = error_msg.split(":")[0].strip() if ":" in error_msg else "AGENT_SIGNATURE_INVALID"
        status = ERROR_STATUS.get(code, 403)
        return JSONResponse(
            status_code=status,
            content={"error": code, "detail": error_msg,
                     "policyVersion": POLICY_VERSION},
        )

    # Auth verified — record in audit
    note(conn, proof.challenge_id, "AUTH_VERIFIED", proof.agent_kid,
         {"policy_version": POLICY_VERSION, "rationale": proof.rationale})

    # Replay resolution
    replay = replay_resolve(conn, proof.jti, proof.resource_hash, proof.challenge_id)
    if replay.action == "REPLAY":
        resp = JSONResponse(
            status_code=replay.status_code or 200,
            content=replay.body if isinstance(replay.body, dict) else {},
        )
        for k, v in (replay.headers or {}).items():
            resp.headers[k] = v
        return resp
    elif replay.action == "ERROR":
        resp = JSONResponse(
            status_code=replay.status_code or 409,
            content=replay.body if isinstance(replay.body, dict) else {},
        )
        for k, v in (replay.headers or {}).items():
            resp.headers[k] = v
        return resp

    # Server gate
    try:
        authorize(conn, proof.challenge_id, proof.agent_kid,
                  proof.amount_paise, MERCHANT_ACCOUNT, now_ts)
    except Razor402Error as e:
        # Policy deny — CAS → FAILED
        cas(conn, proof.challenge_id, "FAILED", actor="server_gate",
            event="POLICY_DENY",
            fail_reason=e.code,
            payload={"policy_version": POLICY_VERSION, "code": e.code,
                     "detail": e.detail, "rationale": proof.rationale},
            also=(
                ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
                 (proof.challenge_id,)),
            ))
        note(conn, proof.challenge_id, "POLICY_DENY", proof.agent_kid,
             {"code": e.code, "detail": e.detail, "rationale": proof.rationale,
              "policy_version": POLICY_VERSION})
        return JSONResponse(
            status_code=e.status,
            content=e.to_dict(),
        )

    # Policy allow
    note(conn, proof.challenge_id, "POLICY_ALLOW", proof.agent_kid,
         {"policy_version": POLICY_VERSION, "rationale": proof.rationale,
          "amount_paise": proof.amount_paise})

    # CAS ISSUED → VERIFIED
    cas(conn, proof.challenge_id, "VERIFIED", actor="gateway",
        event="AUTH_VERIFIED",
        rationale=proof.rationale,
        payload={"policy_version": POLICY_VERSION})

    # Mandate check
    from core.catalog import AGENT_POLICY
    policy = AGENT_POLICY.get(proof.agent_kid)
    mandate_token = None
    if policy:
        mandate_token = policy.get("mandate_token")
        # Check mandate allowance
        mandate = conn.execute(
            "SELECT blocked_paise, debited_paise FROM mandates WHERE token=?",
            (mandate_token,)
        ).fetchone()
        if mandate:
            if mandate["debited_paise"] + proof.amount_paise > mandate["blocked_paise"]:
                cas(conn, proof.challenge_id, "FAILED", actor="gateway",
                    event="MANDATE_CHECK_FAILED",
                    fail_reason="MANDATE_ALLOWANCE_EXHAUSTED",
                    payload={"policy_version": POLICY_VERSION},
                    also=(
                        ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
                         (proof.challenge_id,)),
                    ))
                return JSONResponse(
                    status_code=402,
                    content={"error": "MANDATE_ALLOWANCE_EXHAUSTED",
                             "detail": f"{mandate['debited_paise']}+{proof.amount_paise} > {mandate['blocked_paise']}"},
                )

    # Settle
    settle_result = settle(conn, adapter, proof.challenge_id,
                           proof.amount_paise, mandate_token)

    if settle_result.status == "in_doubt":
        return JSONResponse(
            status_code=202,
            content={"error": "SETTLEMENT_IN_DOUBT",
                     "detail": "Payment status unknown; check back"},
            headers={"Retry-After": "15",
                     "X-Razor402-State": "SETTLEMENT_UNKNOWN"},
        )

    if settle_result.status == "failed":
        return JSONResponse(
            status_code=402,
            content={"error": "PAYMENT_FAILED", "detail": "Payment declined"},
        )

    # Fulfil
    upstream_url = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9000")
    fulfil_result = fulfil(conn, adapter, proof.challenge_id, upstream_url)

    if "error" in fulfil_result and fulfil_result["error"] == "UPSTREAM_FULFILMENT_FAILED":
        # Compensation happened
        resp = JSONResponse(
            status_code=502,
            content=fulfil_result,
        )
        resp.headers["X-Razor402-State"] = "COMPENSATED"
        if settle_result.payment_id:
            resp.headers["X-PAYMENT-RESPONSE"] = json.dumps({
                "paymentId": settle_result.payment_id,
                "refundId": fulfil_result.get("settlement", {}).get("refundId"),
                "status": "refunded",
                "paymentMode": settle_result.payment_mode or "harness",
            })
        return resp

    # Success
    status_code = fulfil_result.get("status_code", 200)
    resp_body = fulfil_result.get("body", {})

    resp = JSONResponse(
        status_code=status_code,
        content=resp_body if isinstance(resp_body, dict) else {},
    )
    resp.headers["X-Razor402-State"] = "FULFILLED"
    resp.headers["X-Razor402-Replay"] = "false"
    resp.headers["X-PAYMENT-RESPONSE"] = json.dumps(
        fulfil_result.get("payment_response", {}))
    return resp


def _mint_challenge(conn, keys, pubs, kid, item_id, item,
                    method, path, query, body, now_ts):
    """Mint a 402 challenge."""
    cid = uuid7()
    nonce = b64u(secrets.token_bytes(16))
    r_hash = resource_hash(method, path, query, body)
    price = item["price_paise"]

    # Build accepts[]
    accepts_list = build_accepts(conn, kid, item_id, now_ts)
    if not accepts_list:
        accepts_list = [{"amountPaise": price, "priceBasis": PRICE_BASIS_UNIT}]

    # Build full accepts entries
    challenge_jws_list = []
    full_accepts = []

    for i, acc in enumerate(accepts_list):
        amount = acc["amountPaise"]
        price_basis = acc.get("priceBasis", PRICE_BASIS_UNIT)
        option_item_id = acc.get("itemId", item_id)

        accept_entry = {
            "scheme": "razorpay-inr",
            "network": "razorpay-test",
            "asset": "INR",
            "decimals": 2,
            "amountPaise": amount,
            "payTo": MERCHANT_ACCOUNT,
            "resource": path,
            "resourceHash": r_hash,
            "description": CATALOG.get(option_item_id, item)["title"],
            "mimeType": "application/json",
            "extra": {
                "challengeId": cid,
                "nonce": nonce,
                "agentKid": kid,
                "iat": now_ts,
                "exp": now_ts + CHALLENGE_TTL_S,
                "priceBasis": price_basis,
                "policyVersion": POLICY_VERSION,
                "mandateRef": "upi_sbmd",
            },
        }

        # Add pass-specific extra fields
        if "triggeredBy" in acc:
            accept_entry["extra"]["triggeredBy"] = acc["triggeredBy"]
        if "breakEvenCalls" in acc:
            accept_entry["extra"]["breakEvenCalls"] = acc["breakEvenCalls"]

        full_accepts.append(accept_entry)

        # Sign each option
        if "gateway" in keys:
            jws = sign_jws(accept_entry, keys["gateway"], "gateway")
        else:
            jws = ""
        challenge_jws_list.append(jws)

    # Insert txn row at ISSUED
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, "
        "req_method, req_path, req_query, req_body, "
        "created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, "ISSUED", RANK["ISSUED"], kid, item_id,
         r_hash, full_accepts[0]["amountPaise"],
         full_accepts[0].get("extra", {}).get("priceBasis", PRICE_BASIS_UNIT),
         method, path, query, body, now_ts, now_ts)
    )

    # Audit
    from state.ledger import _append_audit
    _append_audit(conn, cid, "CHALLENGE_ISSUED", None, "ISSUED", RANK["ISSUED"],
                  "gateway", {"policy_version": POLICY_VERSION,
                              "item_id": item_id, "amount_paise": price})

    # Build response
    response_body = {
        "x402Version": 1,
        "razor402Version": "0.1.0",
        "error": "PAYMENT_REQUIRED",
        "accepts": full_accepts,
    }

    if len(challenge_jws_list) == 1:
        response_body["challengeJws"] = challenge_jws_list[0]
    else:
        response_body["challengeJwsList"] = challenge_jws_list

    resp = JSONResponse(
        status_code=402,
        content=response_body,
        headers={
            "Cache-Control": "no-store",
            "WWW-Authenticate": f'Razor402 realm="buildbroker", scheme="razorpay-inr", max-age={CHALLENGE_TTL_S}',
            "X-Razor402-Challenge-Id": cid,
        },
    )
    return resp


async def _forward_free(request: Request, item_id: str, pass_info: dict):
    """Forward a pass-covered request to upstream for free."""
    import httpx

    upstream_url = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9000")
    try:
        resp = httpx.post(
            f"{upstream_url}/provision/{item_id}",
            headers={"X-Challenge-Id": pass_info.get("challenge_id", "pass")},
            timeout=8.0,
        )
        result = JSONResponse(
            status_code=resp.status_code,
            content=resp.json() if resp.status_code < 400 else {"error": resp.text},
        )
        result.headers["X-Razor402-Pass"] = "true"
        return result
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": "UPSTREAM_UNREACHABLE", "detail": str(e)},
        )
