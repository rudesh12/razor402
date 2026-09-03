"""Seed the database with mandates and reset chaos mode."""
import os
import sys
import sqlite3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from state.ledger import init_db
from state.db import get_connection
from core.catalog import AGENT_POLICY


def main():
    db_path = os.environ.get("DB_PATH", "razor402.db")
    print(f"Seeding database: {db_path}")

    init_db(db_path)
    conn = get_connection(db_path)

    # Seed mandates
    for kid, policy in AGENT_POLICY.items():
        token = policy["mandate_token"]
        blocked = policy["mandate_blocked_paise"]
        conn.execute(
            "INSERT OR REPLACE INTO mandates (token, agent_kid, blocked_paise, debited_paise) "
            "VALUES (?, ?, ?, 0)",
            (token, kid, blocked)
        )
    conn.commit()

    # Reset merchant chaos mode via HTTP (best effort)
    try:
        import httpx
        upstream = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9000")
        httpx.post(f"{upstream}/chaos", json={"mode": "ok"}, timeout=2.0)
        print("Merchant chaos reset to 'ok'")
    except Exception:
        print("Merchant not reachable; chaos not reset (ok for local dev)")

    print("Seed complete.")
    conn.close()


if __name__ == "__main__":
    main()
