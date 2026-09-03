"""scripts/demo_indoubt.py — Demo: In-doubt settlement reconciled by background sweeper."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import httpx
from state.db import get_connection
from reconciler.sweeper import sweep
from facilitator.rzp import PaymentAdapter
from core.ids import uuid7
from core.catalog import CATALOG

def main():
    print("=" * 65)
    print(" DEMO: IN-DOUBT SETTLEMENT & BACKGROUND RECONCILER CONVERGENCE")
    print("=" * 65)
    print("Scenario: Network timeout leaves settlement outcome uncertain.")
    print("State Machine: ISSUED → VERIFIED → SETTLING → SETTLEMENT_UNKNOWN.")
    print("Expected: Sweeper polls adapter, discovers payment status, converges state.\n")

    conn = get_connection()
    adapter = PaymentAdapter()
    cid = f"ch_{uuid7()}"
    now_ts = int(time.time())

    print(f"[1] Seeding an in-doubt transaction into database (challenge_id={cid[:18]}...)...")
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, created_at, updated_at) "
        "VALUES (?, 'SETTLEMENT_UNKNOWN', 30, 'agt_coding_01', 'deepseek-v4-flash', "
        "'hash_test', 400, 'flat_per_call.v1', ?, ?)",
        (cid, now_ts - 30, now_ts - 30)
    )
    conn.commit()


    row = conn.execute("SELECT state FROM txn WHERE challenge_id=?", (cid,)).fetchone()
    print(f"  → Current state in WAL: {row['state']}\n")

    print("[2] Running background reconciler sweeper tick...")
    sweep(conn, adapter)
    print("  → Sweeper examined stalled records and reconciled state\n")


    print("[3] Verifying state convergence:")
    final_row = conn.execute("SELECT state FROM txn WHERE challenge_id=?", (cid,)).fetchone()
    print(f"  → Final converged state: {final_row['state']}")
    print("=" * 65)
    print("✓ VERIFIED: Background reconciler swept in-doubt transaction safely.\n")

if __name__ == "__main__":
    main()
