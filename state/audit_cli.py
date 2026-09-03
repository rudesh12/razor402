"""state/audit_cli.py — CLI for audit chain operations."""
import sys
import json
import sqlite3
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from state.db import get_connection
from state.ledger import init_db, verify_chain

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def cmd_verify():
    db_path = os.environ.get("DB_PATH", "razor402.db")
    init_db(db_path)
    conn = get_connection(db_path)
    valid, seq = verify_chain(conn)
    if valid:
        print(f"✓ Audit chain valid. Head at seq={seq}")
    else:
        print(f"✗ Audit chain BROKEN at seq={seq}")
        sys.exit(1)


def cmd_head():
    db_path = os.environ.get("DB_PATH", "razor402.db")
    init_db(db_path)
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT seq, ts, challenge_id, event, from_state, to_state, actor, "
        "entry_hash FROM audit ORDER BY seq DESC LIMIT 10"
    ).fetchall()
    for r in rows:
        print(f"  seq={r['seq']} event={r['event']} "
              f"{'→'+r['to_state'] if r['to_state'] else ''} "
              f"actor={r['actor']} hash={r['entry_hash'][:16]}…")


def cmd_export():
    db_path = os.environ.get("DB_PATH", "razor402.db")
    init_db(db_path)
    conn = get_connection(db_path)
    rows = conn.execute("SELECT * FROM audit ORDER BY seq ASC").fetchall()
    entries = [dict(r) for r in rows]
    print(json.dumps(entries, indent=2))


def cmd_tamper():
    """Demo helper: mutate one audit payload via raw connection.
    WARNING: This is a demo-only tool. Do not use in production."""
    print("⚠ DEMO-ONLY: Tampering with audit entry for demonstration purposes.")
    db_path = os.environ.get("DB_PATH", "razor402.db")

    # Use a raw connection to bypass the trigger
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute("PRAGMA journal_mode=WAL")

    # Disable the trigger temporarily
    try:
        raw_conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
    except Exception:
        pass

    row = raw_conn.execute(
        "SELECT seq, payload FROM audit ORDER BY seq DESC LIMIT 1"
    ).fetchone()

    if row is None:
        print("No audit entries to tamper with.")
        raw_conn.close()
        return

    seq = row[0]
    payload = json.loads(row[1])
    payload["tampered"] = True
    raw_conn.execute(
        "UPDATE audit SET payload=? WHERE seq=?",
        (json.dumps(payload), seq)
    )
    raw_conn.commit()

    # Re-create the trigger
    raw_conn.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit "
        "BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END"
    )
    raw_conn.commit()
    raw_conn.close()

    print(f"Tampered audit entry at seq={seq}")
    print("Run 'verify' to detect the tampering.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m state.audit_cli {verify|head|export|tamper}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "verify":
        cmd_verify()
    elif cmd == "head":
        cmd_head()
    elif cmd == "export":
        cmd_export()
    elif cmd == "tamper":
        cmd_tamper()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
