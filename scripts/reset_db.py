"""scripts/reset_db.py — Clear all transactions, audit logs, and reset the database."""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core.catalog import AGENT_POLICY
from state.ledger import init_db

def reset_database(db_path: str = "razor402.db"):
    print(f"Clearing and resetting database: {db_path}...")

    # Ensure schema exists first
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")

    # Drop triggers that prevent deletion from append-only audit table
    conn.execute("DROP TRIGGER IF EXISTS audit_no_delete")
    conn.execute("DROP TRIGGER IF EXISTS audit_no_update")

    tables = [
        "txn",
        "audit",
        "budget_reservations",
        "jti_seen",
        "passes",
        "webhook_events",
        "checkpoints",
        "mandates",
    ]

    for table in tables:
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass

    # Reset SQLite autoincrement sequences
    try:
        conn.execute("DELETE FROM sqlite_sequence")
    except sqlite3.OperationalError:
        pass

    conn.commit()

    # Re-apply schema to restore triggers and indexes
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "state", "schema.sql"
    )
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()

    # Seed baseline agent mandates
    for kid, policy in AGENT_POLICY.items():
        token = policy["mandate_token"]
        blocked = policy["mandate_blocked_paise"]
        conn.execute(
            "INSERT OR REPLACE INTO mandates (token, agent_kid, blocked_paise, debited_paise) "
            "VALUES (?, ?, ?, 0)",
            (token, kid, blocked)
        )
    conn.commit()
    conn.close()

    # Reset merchant chaos mode if running
    try:
        import httpx
        upstream = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9000")
        httpx.post(f"{upstream}/chaos", json={"mode": "ok"}, timeout=1.5)
        print("✓ Merchant chaos mode reset to 'ok'")
    except Exception:
        pass

    # Reset console operator revocation if running
    try:
        from gateway.console_api import set_envelope_revoked
        set_envelope_revoked(False)
    except Exception:
        pass

    print(f"✓ Database '{db_path}' successfully cleared and reseeded.")


if __name__ == "__main__":
    db_file = os.environ.get("DB_PATH", "razor402.db")
    reset_database(db_file)
