"""merchant/app.py — BuildBroker upstream merchant + /chaos endpoint."""
import hashlib
import time
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from core.catalog import CATALOG, FULFIL_DEADLINE_S

app = FastAPI(title="BuildBroker Merchant")

# Chaos state
_chaos_mode = "ok"  # ok | crash | hang | 500


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/provision/{item_id}")
async def provision(item_id: str, request: Request):
    global _chaos_mode

    if _chaos_mode == "crash":
        raise HTTPException(status_code=500, detail="Chaos: crash")
    if _chaos_mode == "500":
        return JSONResponse(status_code=500, content={"error": "Chaos: 500"})
    if _chaos_mode == "hang":
        time.sleep(FULFIL_DEADLINE_S + 2)
        return JSONResponse(status_code=500, content={"error": "Chaos: hang exceeded deadline"})

    if item_id not in CATALOG:
        raise HTTPException(status_code=404, detail=f"Unknown item: {item_id}")

    # Extract challenge_id from request headers or query
    challenge_id = request.headers.get("X-Challenge-Id", "unknown")

    # Deterministic sandbox key
    sandbox_key = f"sb_sk_{item_id}_{hashlib.sha256((item_id + challenge_id).encode()).hexdigest()[:12]}"

    # Build provisioning payload
    valid_until = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    item = CATALOG[item_id]
    payload = {
        "item_id": item_id,
        "provisioned_resource": {
            "sandbox_api_key": sandbox_key,
            "quota": _get_quota(item_id, item),
            "endpoint": f"https://api.buildbroker.dev/v1/{_get_endpoint_path(item_id)}",
            "valid_until": valid_until,
        },
    }
    return payload


def _get_quota(item_id: str, item: dict) -> dict:
    if item_id == "deepseek-v3-tokens":
        return {"tokens": 100_000}
    elif item_id == "qdrant-vector-query":
        return {"queries": 1}
    elif item_id == "market-snapshot":
        return {"snapshots": 1}
    elif item_id == "day-pass":
        return {"queries": "unlimited", "valid_hours": 24}
    elif item_id == "enterprise-gpu-node":
        return {"hours": 1, "gpus": 8}
    return {"units": 1}


def _get_endpoint_path(item_id: str) -> str:
    paths = {
        "deepseek-v3-tokens": "inference/generate",
        "qdrant-vector-query": "vectors/search",
        "market-snapshot": "market/snapshot",
        "day-pass": "vectors/search",
        "enterprise-gpu-node": "compute/provision",
    }
    return paths.get(item_id, "provision")


@app.post("/chaos")
async def set_chaos(request: Request):
    global _chaos_mode
    body = await request.json()
    mode = body.get("mode", "ok")
    if mode not in ("ok", "crash", "hang", "500"):
        raise HTTPException(status_code=400, detail=f"Invalid chaos mode: {mode}")
    _chaos_mode = mode
    return {"chaos": _chaos_mode}


@app.get("/chaos")
async def get_chaos():
    return {"chaos": _chaos_mode}
