"""state/ledger.py — CAS, audit chain, note, bump, verify_chain."""
import hashlib
import json
import os

from core.canonical import jcs
from core.clock import now
from state.states import RANK, ALLOWED_FROM, TERMINAL


def init_db(db_path: str | None = None):
    """Initialize the database schema idempotently."""
    from state.db import get_connection
    conn = get_connection(db_path)
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r") as f:
        conn.executescript(f.read())


def _compute_entry_hash(prev_hash: str, challenge_id: str | None, event: str,
                        to_state: str | None, to_rank: int | None,
                        actor: str, payload: dict) -> str:
    """
    entry_hash = SHA256(prev_hash|challenge_id|event|to_state|to_rank|actor|jcs(payload))
    joined with literal |, None rendered as empty string
    """
    parts = [
        prev_hash,
        challenge_id or "",
        event,
        to_state or "",
        str(to_rank) if to_rank is not None else "",
        actor,
        jcs(payload),
    ]
    content = "|".join(parts)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _get_prev_hash(conn) -> str:
    """Get the hash of the last audit entry, or the genesis hash."""
    row = conn.execute("SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
    if row:
        return row["entry_hash"]
    return "0" * 64


def _append_audit(conn, challenge_id: str | None, event: str,
                  from_state: str | None, to_state: str | None,
                  to_rank: int | None, actor: str, payload: dict) -> int:
    """Append an entry to the audit chain. Returns the new seq."""
    ts = now()
    prev_hash = _get_prev_hash(conn)
    entry_hash = _compute_entry_hash(prev_hash, challenge_id, event, to_state,
                                     to_rank, actor, payload)

    cursor = conn.execute(
        "INSERT INTO audit (ts, challenge_id, event, from_state, to_state, to_rank, "
        "actor, payload, prev_hash, entry_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ts, challenge_id, event, from_state, to_state, to_rank,
         actor, json.dumps(payload), prev_hash, entry_hash)
    )
    return cursor.lastrowid  # type: ignore


def cas(conn, challenge_id: str, to_state: str, *, actor: str,
        event: str | None = None, payload: dict | None = None,
        also: tuple[tuple[str, tuple], ...] = (),
        attempt_inc: int = 0, **fields) -> tuple[str, int | None]:
    """
    Atomic: conditional state transition + optional side-writes + audit append.
    All inside one BEGIN IMMEDIATE. Returns (result, audit_seq).
    result ∈ {"APPLIED", "STALE", "ILLEGAL", "ORPHAN"}
    """
    if payload is None:
        payload = {}
    if event is None:
        event = to_state

    to_rank = RANK[to_state]
    allowed_from = ALLOWED_FROM[to_state]

    # Add policy_version and payment_mode to payload when available
    if "policy_version" not in payload and fields.get("payment_mode"):
        from core.catalog import POLICY_VERSION
        payload["policy_version"] = POLICY_VERSION
    if "payment_mode" in fields and fields["payment_mode"]:
        payload["payment_mode"] = fields["payment_mode"]

    # Build allowed_from placeholders
    if allowed_from:
        placeholders = ",".join("?" for _ in allowed_from)
        params = [to_state, to_rank, now(), challenge_id, to_rank] + list(allowed_from)
    else:
        # ISSUED has empty allowed_from — should not be used with cas
        raise ValueError("Cannot CAS to ISSUED (use INSERT)")

    # Build SET clause for extra fields
    set_parts = ["state=?", "rank=?", "updated_at=?"]
    set_params = [to_state, to_rank, now()]

    for field_name in ("order_id", "payment_id", "refund_id", "settled_via",
                       "payment_mode", "fail_reason", "resp_status", "resp_body",
                       "resp_sha256"):
        if field_name in fields:
            set_parts.append(f"{field_name}=?")
            set_params.append(fields[field_name])

    if attempt_inc:
        set_parts.append("attempts=attempts+?")
        set_params.append(attempt_inc)

    if "next_at" in fields:
        set_parts.append("next_at=?")
        set_params.append(fields["next_at"])

    if "lease_until" in fields:
        set_parts.append("lease_until=?")
        set_params.append(fields["lease_until"])

    if "rationale" in fields:
        set_parts.append("rationale=?")
        set_params.append(fields["rationale"])

    set_clause = ", ".join(set_parts)
    update_params = set_params + [challenge_id, to_rank] + list(allowed_from)

    update_sql = (
        f"UPDATE txn SET {set_clause} "
        f"WHERE challenge_id=? AND rank < ? AND state IN ({placeholders})"
    )

    cursor = conn.execute(update_sql, update_params)

    if cursor.rowcount == 1:
        # Read from_state for audit
        row = conn.execute(
            "SELECT state FROM txn WHERE challenge_id=?", (challenge_id,)
        ).fetchone()
        from_state = to_state  # It's already transitioned

        # Execute side-writes
        for sql, params in also:
            conn.execute(sql, params)

        # Append audit
        seq = _append_audit(conn, challenge_id, event, None, to_state,
                            to_rank, actor, payload)
        return ("APPLIED", seq)

    # rowcount == 0: re-read
    row = conn.execute(
        "SELECT state, rank FROM txn WHERE challenge_id=?", (challenge_id,)
    ).fetchone()

    if row is None:
        seq = _append_audit(conn, challenge_id, "ORPHAN_EVENT", None, to_state,
                            to_rank, actor, payload)
        return ("ORPHAN", seq)

    current_rank = row["rank"]
    current_state = row["state"]

    if current_rank >= to_rank:
        seq = _append_audit(conn, challenge_id, "NOOP_STALE_EVENT",
                            current_state, to_state, to_rank, actor, payload)
        return ("STALE", seq)

    seq = _append_audit(conn, challenge_id, "REJECT_ILLEGAL_TRANSITION",
                        current_state, to_state, to_rank, actor, payload)
    return ("ILLEGAL", seq)


def note(conn, challenge_id: str, event: str, actor: str,
         payload: dict | None = None) -> int:
    """Audit append with no transition."""
    if payload is None:
        payload = {}
    seq = _append_audit(conn, challenge_id, event, None, None, None, actor, payload)
    return seq


def bump(conn, challenge_id: str, *, inc: int = 1, next_at: int | None = None,
         reason: str | None = None, event: str = "FULFIL_ATTEMPT_FAILED") -> int:
    """Increment attempts and append a note. NO state transition."""
    update_parts = ["attempts=attempts+?"]
    params: list = [inc]

    if next_at is not None:
        update_parts.append("next_at=?")
        params.append(next_at)

    params.append(challenge_id)
    conn.execute(
        f"UPDATE txn SET {', '.join(update_parts)} WHERE challenge_id=?",
        params
    )

    payload = {}
    if reason:
        payload["reason"] = reason
    return note(conn, challenge_id, event, "system", payload)


def verify_chain(conn) -> tuple[bool, int]:
    """
    Verify the audit hash chain.
    Returns (valid: bool, seq_or_head: int).
    On failure, seq is the first broken entry.
    """
    rows = conn.execute(
        "SELECT seq, challenge_id, event, to_state, to_rank, actor, payload, "
        "prev_hash, entry_hash FROM audit ORDER BY seq ASC"
    ).fetchall()

    if not rows:
        return (True, 0)

    prev_hash = "0" * 64
    for row in rows:
        payload = json.loads(row["payload"])
        expected = _compute_entry_hash(
            prev_hash,
            row["challenge_id"],
            row["event"],
            row["to_state"],
            row["to_rank"],
            row["actor"],
            payload,
        )
        if expected != row["entry_hash"]:
            return (False, row["seq"])
        prev_hash = row["entry_hash"]

    return (True, rows[-1]["seq"])


def claim_lease(conn, states: list[str], limit: int = 20,
                now_ts: int | None = None) -> list:
    """Claim rows for processing by setting lease_until."""
    if now_ts is None:
        now_ts = now()

    placeholders = ",".join("?" for _ in states)
    rows = conn.execute(
        f"SELECT * FROM txn WHERE state IN ({placeholders}) "
        f"AND next_at <= ? AND lease_until < ? "
        f"ORDER BY rank ASC, created_at ASC LIMIT ?",
        list(states) + [now_ts, now_ts, limit]
    ).fetchall()

    # Set lease
    for row in rows:
        conn.execute(
            "UPDATE txn SET lease_until=? WHERE challenge_id=?",
            (now_ts + 60, row["challenge_id"])
        )

    return rows


def checkpoint(conn, sk, every: int = 50):
    """Sign a checkpoint every N audit entries."""
    from core.crypto import sign_jws, b64u
    last_cp = conn.execute(
        "SELECT MAX(seq) as m FROM checkpoints"
    ).fetchone()
    last_seq = last_cp["m"] if last_cp and last_cp["m"] else 0

    last_audit = conn.execute(
        "SELECT MAX(seq) as m FROM audit"
    ).fetchone()
    audit_head = last_audit["m"] if last_audit and last_audit["m"] else 0

    if audit_head - last_seq >= every:
        row = conn.execute(
            "SELECT entry_hash FROM audit WHERE seq=?", (audit_head,)
        ).fetchone()
        if row:
            ts = now()
            sig = sign_jws({"seq": audit_head, "hash": row["entry_hash"], "ts": ts},
                           sk, "gateway")
            conn.execute(
                "INSERT INTO checkpoints (seq, entry_hash, signature, created_at) "
                "VALUES (?, ?, ?, ?)",
                (audit_head, row["entry_hash"], sig, ts)
            )
