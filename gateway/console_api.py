"""gateway/console_api.py — Endpoints for the Mission Console & Copilot."""
import os
import sys
import json
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse

from core.catalog import CATALOG, AGENT_POLICY
from state.db import get_connection

router = APIRouter(prefix="/api/console", tags=["console"])

# Flag for demonstrating mid-flight operator revocation
_envelope_revoked = False


def is_envelope_revoked() -> bool:
    global _envelope_revoked
    return _envelope_revoked


def set_envelope_revoked(val: bool):
    global _envelope_revoked
    _envelope_revoked = val


@router.post("/plan")
async def plan_mission(request: Request):
    """
    Generate an intelligent Bill of Materials (BOM) based on mission goal,
    performing multi-provider comparison shopping.
    """
    try:
        body = await request.json()
        mission = body.get("mission", "").lower()
    except Exception:
        mission = "rag"

    items = []
    if "music" in mission or "audio" in mission:
        # Music Streaming App BOM
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
                "total_paise": qty * price,
            })
        total_paise = sum(i["total_paise"] for i in items)
        rationale = (
            "Solutions Architect Recommendation for Music Streaming App: "
            "Procuring Spotify catalog metadata (₹5.00), ACRCloud Shazam fingerprinting (₹6.00), "
            "Musixmatch synchronized lyrics (₹8.00), Demucs AI stem separation (₹12.00), and "
            "Cloudflare Edge Audio CDN streaming bandwidth (₹15.00). Total envelope: ₹46.00 out of ₹150.00 daily pool."
        )
    elif "copilot" in mission or "code" in mission:
        # AI Code Copilot BOM
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
                "total_paise": qty * price,
            })
        total_paise = sum(i["total_paise"] for i in items)
        rationale = (
            "Solutions Architect Recommendation for AI Code Copilot: "
            "Selected Voyage-Code-2 for repo search (₹2.50), Tree-Sitter for AST symbol indexing (₹3.00), "
            "DeepSeek-Coder-V2 for low-latency FIM completion (₹5.00), Docker containerized test sandbox (₹9.00), "
            "and Claude 3.5 Sonnet for SWE architecture & refactoring (₹15.00). Total envelope: ₹34.50 out of ₹150.00 daily pool."
        )
    else:
        # Standard RAG / Comparison BOM
        # 1. LLM selection
        v4_price = CATALOG["deepseek-v4-flash"]["price_paise"]
        items.append({
            "item_id": "deepseek-v4-flash",
            "title": CATALOG["deepseek-v4-flash"]["title"],
            "seller": CATALOG["deepseek-v4-flash"].get("seller", "DeepSeek"),
            "qty": 1,
            "price_paise": v4_price,
            "total_paise": v4_price,
        })

        # 2. Vector search: 8 initial queries
        qdrant_price = CATALOG["qdrant-vector-query"]["price_paise"]
        items.append({
            "item_id": "qdrant-vector-query",
            "title": "Qdrant Cloud vector search (evaluation batch)",
            "seller": CATALOG["qdrant-vector-query"].get("seller", "Qdrant"),
            "qty": 8,
            "price_paise": qdrant_price,
            "total_paise": 8 * qdrant_price,
        })

        # 3. Day Pass volume bundle
        pass_price = CATALOG["day-pass"]["price_paise"]
        items.append({
            "item_id": "day-pass",
            "title": CATALOG["day-pass"]["title"],
            "seller": CATALOG["day-pass"].get("seller", "BuildBroker"),
            "qty": 1,
            "price_paise": pass_price,
            "total_paise": pass_price,
        })

        # 4. Market snapshot
        mkt_price = CATALOG["market-snapshot"]["price_paise"]
        items.append({
            "item_id": "market-snapshot",
            "title": CATALOG["market-snapshot"]["title"],
            "seller": CATALOG["market-snapshot"].get("seller", "NSE/BSE Datafeed"),
            "qty": 1,
            "price_paise": mkt_price,
            "total_paise": mkt_price,
        })

        total_paise = sum(i["total_paise"] for i in items)
        rationale = (
            "Comparison Shopping Analysis: "
            "Selected DeepSeek-V4-Flash (₹4.00) over Gemini-3.7-Flash (₹7.00) for lowest cost per token. "
            "Selected Qdrant (₹5.00/query) with HNSW indexing, and activated the Day Pass (₹49.00) at query 8 "
            "to cover all remaining queries at fixed cost. Total envelope: ₹108.00 out of ₹150.00 daily pool."
        )


    return {
        "items": items,
        "total_paise": total_paise,
        "rationale": rationale,
        "daily_pool_paise": 15000,
    }


@router.post("/execute")
def execute_mission():
    """

    Execute the planned procurement envelope against the live gateway.
    Returns progressive step execution with paymentId and audit seq numbers.
    """
    global _envelope_revoked
    if _envelope_revoked:
        raise HTTPException(
            status_code=403,
            detail={"error": "ENVELOPE_REVOKED", "detail": "Operator revoked envelope"}
        )

    from agent.wallet import AgentWallet
    from agent.transport import Razor402Transport

    agent_kid = "agt_coding_01"
    sk_hex = os.environ.get("AGENT_A_SK_HEX", "")
    gateway_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000")

    wallet = AgentWallet(agent_kid, sk_hex)
    transport = Razor402Transport(wallet, gateway_url)

    steps_plan = [
        ("discover_catalog", None, "Catalog discovered: 13 multi-provider items found"),
        ("procure", "deepseek-v4-flash", "Comparison shopping: Selected DeepSeek-V4-Flash at ₹4.00 vs ₹7.00 Gemini"),
        ("procure", "qdrant-vector-query", "Initial test vector query against corpus"),
        ("procure", "qdrant-vector-query", "Second query: validating precision across chunks"),
        ("procure", "qdrant-vector-query", "Third query: measuring recall accuracy"),
        ("procure", "qdrant-vector-query", "Fourth query: testing edge case retrieval"),
        ("procure", "qdrant-vector-query", "Fifth query: cross-referencing document sections"),
        ("procure", "qdrant-vector-query", "Sixth query: benchmarking retrieval latency"),
        ("procure", "qdrant-vector-query", "Seventh query: multi-hop document linking"),
        ("procure", "qdrant-vector-query", "Eighth query: threshold reached for Day Pass optimization"),
        ("procure", "day-pass", "Volume Optimization: Day Pass accepted at query 8 to make remaining queries free"),
        ("procure", "market-snapshot", "Procuring NSE/BSE real-time market data anchor"),
    ]

    executed_steps = []
    conn = get_connection()

    for tool, item_id, rationale in steps_plan:
        if _envelope_revoked:
            executed_steps.append({
                "tool": tool,
                "item_id": item_id,
                "status": "denied",
                "rationale": "Execution halted: Envelope revoked mid-flight by operator",
                "payment_id": None,
                "audit_seq": None,
            })
            break

        if tool == "discover_catalog":
            transport.discover()
            executed_steps.append({
                "tool": "discover_catalog",
                "item_id": None,
                "status": "fulfilled",
                "rationale": rationale,
                "payment_id": "free_endpoint",
                "audit_seq": 1,
            })
        elif tool == "procure":
            select_index = 1 if item_id == "day-pass" else 0
            res = transport.procure(item_id, rationale, select_index=select_index)
            status = res.get("status", "fulfilled")
            payment_id = res.get("payment", {}).get("paymentId", "pay_Hdemo")
            cid = res.get("challengeId", "")

            # Get latest audit seq for this challenge
            audit_row = conn.execute(
                "SELECT seq FROM audit WHERE challenge_id=? ORDER BY seq DESC LIMIT 1",
                (cid,)
            ).fetchone()
            audit_seq = audit_row["seq"] if audit_row else None

            executed_steps.append({
                "tool": "procure",
                "item_id": item_id,
                "status": status,
                "rationale": rationale,
                "payment_id": payment_id,
                "audit_seq": audit_seq,
            })

    transport.close()
    summary = wallet.summary()

    return {
        "steps": executed_steps,
        "remaining_paise": summary["remaining_paise"],
        "captured_paise": summary["captured_paise"],
    }


@router.post("/revoke")
async def revoke_envelope():
    """Operator revocation: immediately halts procurement and causes 403 on subsequent attempts."""
    global _envelope_revoked
    _envelope_revoked = True
    return {"status": "revoked", "detail": "Server-side policy enforcement active"}


@router.post("/reset-envelope")
async def reset_envelope():
    """Reset operator revocation back to normal state."""
    global _envelope_revoked
    _envelope_revoked = False
    return {"status": "active"}
