"""scripts/demo_replay.py — Demo: 8 concurrent identical requests with JTI deduplication."""
import os
import sys
import concurrent.futures

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import httpx
from agent.wallet import AgentWallet
from core.ids import uuid7

def main():
    print("=" * 65)
    print(" DEMO: REPLAY & IDEMPOTENCY SAFETY (8 CONCURRENT IDENTICAL REQUESTS)")
    print("=" * 65)
    print("Scenario: 8 concurrent requests arrive with the identical JTI token.")
    print("Expected: Exactly 1 payment settles; 7 return cached byte-identical replays.\n")

    gateway_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000")
    sk_hex = os.environ.get("AGENT_A_SK_HEX", "")
    wallet = AgentWallet("agt_coding_01", sk_hex)

    from core.crypto import sign_jws
    from core.clock import now

    # 1. Get 402 challenge
    with httpx.Client(base_url=gateway_url) as client:
        r402 = client.post("/provision/deepseek-v4-flash")
        assert r402.status_code == 402
        challenge = r402.json()
        challenge_jws = r402.headers.get("X-CHALLENGE", "")

    # 2. Pre-mint 1 signed authorization token (fixed JTI)
    accept = challenge["accepts"][0]
    challenge_id = accept["extra"]["challengeId"]
    challenge_jws = challenge.get("challengeJws") or challenge.get("challengeJwsList", [""])[0]

    auth_payload = {
        "typ": "razor402.payment-authorization+jws",
        "challengeJws": challenge_jws,
        "challengeId": challenge_id,
        "agentKid": wallet.kid,
        "mandate": {"type": "upi_sbmd", "token": wallet.mandate_token},
        "maxDebitPaise": accept["amountPaise"],
        "rationale": "Concurrent replay test: checking single-settlement guarantee.",
        "jti": f"jti_demo_{uuid7()}",
        "iat": now(),
    }
    auth_jws = sign_jws(auth_payload, wallet.sk, wallet.kid)


    headers = {
        "X-PAYMENT": auth_jws,
        "X-Razor402-Agent": wallet.kid,
        "Content-Type": "application/json",
    }


    # 3. Fire 8 threads simultaneously
    print("Firing 8 simultaneous HTTP requests with identical JTI...")
    results = []
    def send_req(i):
        with httpx.Client(base_url=gateway_url, timeout=30.0) as client:
            resp = client.post("/provision/deepseek-v4-flash", headers=headers)
            return (i, resp.status_code, resp.headers.get("X-Cache", "MISS"), resp.json())

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(send_req, i) for i in range(8)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    payments_seen = set()
    replay_count = 0
    success_count = 0

    for idx, code, cache, body in results:
        pid = body.get("payment", {}).get("paymentId")
        if pid:
            payments_seen.add(pid)
        if cache == "HIT" or body.get("replay"):
            replay_count += 1
        if code == 200:
            success_count += 1
        print(f"  Thread {idx}: Status={code} | X-Cache={cache} | Payment={pid}")

    print()
    print("=" * 65)
    print(f"Results Summary:")
    print(f"  → Total Successful (200 OK): {success_count}/8")
    print(f"  → Cached Replays (X-Cache: HIT): {replay_count}")
    print(f"  → Unique Payments Debited: {len(payments_seen)} (expected: 1)")
    print("=" * 65)
    assert len(payments_seen) <= 1, "CRITICAL: Duplicate payment detected!"
    print("✓ VERIFIED: Single settlement guarantee preserved under concurrency.\n")

if __name__ == "__main__":
    main()
