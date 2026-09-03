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
    cat = item.get("category", "")
    if cat == "llm_inference":
        return {"tokens": item.get("specs", {}).get("context", 100_000)}
    elif "embedding" in item_id:
        return {"tokens": 500_000}
    elif cat == "vector_db":
        return {"queries": 1}
    elif cat == "search_and_data":
        if "search" in item_id:
            return {"queries": 10}
        elif "scrape" in item_id:
            return {"pages": 5}
        elif "browser" in item_id:
            return {"minutes": 5}
        return {"requests": 10}
    elif cat == "financial_data":
        return {"reports": 1}
    elif item_id == "day-pass":
        return {"queries": "unlimited", "valid_hours": 24}
    elif item_id == "enterprise-gpu-node":
        return {"hours": 1, "gpus": 8}
    elif cat == "music_and_audio":
        if "audiocdn" in item_id:
            return {"bandwidth_gb": 10}
        elif "lyrics" in item_id:
            return {"tracks": 100}
        elif "music-id" in item_id or "acrcloud" in item_id:
            return {"queries": 50}
        elif "demucs" in item_id:
            return {"tracks": 1, "stems": 4}
        elif "musicgen" in item_id or "suno" in item_id:
            return {"tracks": 1, "duration_s": 30}
        return {"items": 500}
    elif cat == "code_and_copilot":
        if "coder" in item_id or "sonnet" in item_id:
            return {"tokens": item.get("specs", {}).get("context", 100_000)}
        elif "ast" in item_id or "tree-sitter" in item_id:
            return {"files": 250}
        elif "embedding" in item_id:
            return {"tokens": 1_000_000}
        elif "docker" in item_id or "runner" in item_id:
            return {"test_runs": 10}
        return {"units": 1}
    elif cat == "compute":
        if "interpreter" in item_id:
            return {"minutes": 15, "isolated": True}
        elif "tts" in item_id or "voice" in item_id:
            return {"chars": 5000}
        elif "sdxl" in item_id or "image" in item_id:
            return {"images": 4}
        return {"hours": 1, "vcpus": item.get("specs", {}).get("vcpus", 2)}
    return {"units": 1}


def _get_endpoint_path(item_id: str) -> str:
    cat = CATALOG.get(item_id, {}).get("category", "")
    if cat == "llm_inference":
        return "inference/generate"
    elif "embedding" in item_id:
        return "embeddings/create"
    elif cat == "vector_db" or item_id == "day-pass":
        return "vectors/search"
    elif cat == "search_and_data":
        return "search/query"
    elif cat == "financial_data":
        return "market/feed"
    elif cat == "music_and_audio":
        return "audio/stream"
    elif cat == "code_and_copilot":
        return "copilot/code"
    elif cat == "compute" or item_id == "enterprise-gpu-node":
        return "compute/provision"
    return "provision"





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
