"""tests/test_state_machine.py — T09-T16: State machine and ledger tests."""
import json
import pytest

from state.states import RANK, ALLOWED_FROM, TERMINAL
from state.ledger import cas, note, bump, verify_chain, _append_audit, init_db
from state.db import get_connection
from core.clock import set_clock, reset_clock


# T09
def test_rank_increases_on_every_legal_edge():
    """Property: rank strictly increases on every legal edge."""
    for target_state, from_states in ALLOWED_FROM.items():
        for from_state in from_states:
            assert RANK[target_state] > RANK[from_state], \
                f"Rank does not increase: {from_state}({RANK[from_state]}) -> {target_state}({RANK[target_state]})"


# T10
def test_terminal_states_in_no_allowed_from():
    """Terminal states appear in zero ALLOWED_FROM sets."""
    for state, from_set in ALLOWED_FROM.items():
        for terminal in TERMINAL:
            assert terminal not in from_set, \
                f"Terminal state {terminal} found in ALLOWED_FROM[{state}]"


# T11
def test_all_states_reachable_from_issued():
    """All states are reachable from ISSUED via graph traversal."""
    # Build adjacency
    adj = {}
    for target, froms in ALLOWED_FROM.items():
        for f in froms:
            adj.setdefault(f, set()).add(target)

    # BFS from ISSUED
    visited = set()
    queue = ["ISSUED"]
    while queue:
        state = queue.pop(0)
        if state in visited:
            continue
        visited.add(state)
        for neighbor in adj.get(state, set()):
            if neighbor not in visited:
                queue.append(neighbor)

    # All states should be reachable
    all_states = set(RANK.keys())
    unreachable = all_states - visited
    assert unreachable == set(), f"Unreachable states: {unreachable}"


# T12
def test_cas_applies_legal_transition(tmp_db, fake_clock):
    """APPLIED + audit row created."""
    conn = get_connection(tmp_db)

    # Insert a row at ISSUED
    cid = "test-cas-apply"
    now_ts = fake_clock.time
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, created_at, updated_at) "
        "VALUES (?, 'ISSUED', 10, 'agt_coding_01', 'test', 'sha256:abc', 500, "
        "'flat_per_call.v1', ?, ?)",
        (cid, now_ts, now_ts)
    )

    result, seq = cas(conn, cid, "VERIFIED", actor="test",
                      event="AUTH_VERIFIED", payload={"test": True})
    assert result == "APPLIED"
    assert seq is not None

    # Verify state changed
    row = conn.execute("SELECT state, rank FROM txn WHERE challenge_id=?",
                       (cid,)).fetchone()
    assert row["state"] == "VERIFIED"
    assert row["rank"] == RANK["VERIFIED"]

    # Verify audit row
    audit = conn.execute("SELECT * FROM audit WHERE seq=?", (seq,)).fetchone()
    assert audit is not None
    assert audit["event"] == "AUTH_VERIFIED"


# T13
def test_cas_stale_on_lower_rank(tmp_db, fake_clock):
    """STALE + NOOP_STALE_EVENT when state already past target."""
    conn = get_connection(tmp_db)

    cid = "test-cas-stale"
    now_ts = fake_clock.time
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, created_at, updated_at) "
        "VALUES (?, 'SETTLED', 30, 'agt_coding_01', 'test', 'sha256:abc', 500, "
        "'flat_per_call.v1', ?, ?)",
        (cid, now_ts, now_ts)
    )

    result, seq = cas(conn, cid, "VERIFIED", actor="test")
    assert result == "STALE"

    # State unchanged
    row = conn.execute("SELECT state FROM txn WHERE challenge_id=?",
                       (cid,)).fetchone()
    assert row["state"] == "SETTLED"


# T14
def test_cas_illegal_when_from_set_forbids(tmp_db, fake_clock):
    """ILLEGAL + REJECT_ILLEGAL_TRANSITION when from_set doesn't allow."""
    conn = get_connection(tmp_db)

    cid = "test-cas-illegal"
    now_ts = fake_clock.time
    # ISSUED → SETTLED is illegal (SETTLED requires SETTLING or SETTLEMENT_UNKNOWN)
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, created_at, updated_at) "
        "VALUES (?, 'ISSUED', 10, 'agt_coding_01', 'test', 'sha256:abc', 500, "
        "'flat_per_call.v1', ?, ?)",
        (cid, now_ts, now_ts)
    )

    result, seq = cas(conn, cid, "SETTLED", actor="test")
    assert result == "ILLEGAL"

    # State unchanged
    row = conn.execute("SELECT state FROM txn WHERE challenge_id=?",
                       (cid,)).fetchone()
    assert row["state"] == "ISSUED"


# T15
def test_cas_orphan_on_missing_row(tmp_db, fake_clock):
    """ORPHAN + ORPHAN_EVENT when row doesn't exist."""
    conn = get_connection(tmp_db)

    result, seq = cas(conn, "nonexistent-cid", "VERIFIED", actor="test")
    assert result == "ORPHAN"


# T16
def test_audit_chain_valid_and_tamper_detected(tmp_db, fake_clock):
    """verify_chain() true; raw UPDATE → (False, seq)."""
    conn = get_connection(tmp_db)

    # Append a few audit entries
    _append_audit(conn, "cid1", "EVENT1", None, "ISSUED", 10, "test", {"a": 1})
    _append_audit(conn, "cid1", "EVENT2", "ISSUED", "VERIFIED", 20, "test", {"b": 2})
    seq3 = _append_audit(conn, "cid1", "EVENT3", "VERIFIED", "SETTLING", 25, "test", {"c": 3})

    # Chain should be valid
    valid, head = verify_chain(conn)
    assert valid is True
    assert head == seq3

    # Tamper: bypass trigger with raw connection
    import sqlite3
    raw = sqlite3.connect(tmp_db)
    raw.execute("DROP TRIGGER IF EXISTS audit_no_update")
    raw.execute("UPDATE audit SET payload='{\"tampered\":true}' WHERE seq=?", (seq3,))
    raw.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit "
        "BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END"
    )
    raw.commit()
    raw.close()

    # Refresh connection to see changes
    from state.db import close_connection
    close_connection(tmp_db)
    conn = get_connection(tmp_db)

    valid, broken_seq = verify_chain(conn)
    assert valid is False
    assert broken_seq == seq3
