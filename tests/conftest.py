"""tests/conftest.py — Test fixtures: FakeRazorpay, FakeClock, tmp_db, keys, client."""
import os
import sys
import json
import tempfile
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core.clock import set_clock, reset_clock
from core.errors import PaymentFailed


class FakeClock:
    """Injectable clock for tests."""
    def __init__(self, start: int = 1_770_000_000):
        self._time = start

    def __call__(self):
        return self._time

    def advance(self, seconds: int):
        self._time += seconds

    @property
    def time(self):
        return self._time


class FakeRazorpay:
    """
    Fake payment adapter implementing the same interface as PaymentAdapter.
    With programmable faults and a refund store.
    """
    def __init__(self):
        self.mode = "harness"
        self.call_log: list[tuple[str, dict]] = []
        self.fault: str | None = None
        self._orders: dict[str, dict] = {}
        self._payments: dict[str, dict] = {}
        self._refunds: dict[str, list[dict]] = {}
        self._next_pay_id = 1
        self._next_rfnd_id = 1

    def create_order(self, cid: str, paise: int) -> dict:
        self.call_log.append(("create_order", {"cid": cid, "paise": paise}))

        if self.fault == "timeout":
            import httpx
            raise httpx.TimeoutException("Fake timeout")

        # Check for duplicate receipt
        for oid, order in self._orders.items():
            if order.get("receipt") == cid:
                return order

        oid = f"order_H{self._next_pay_id:04d}"
        self._next_pay_id += 1
        order = {"id": oid, "amount": paise, "currency": "INR",
                 "receipt": cid, "status": "created"}
        self._orders[oid] = order
        return order

    def find_order(self, cid: str) -> dict | None:
        self.call_log.append(("find_order", {"cid": cid}))
        for order in self._orders.values():
            if order.get("receipt") == cid:
                return order
        return None

    def order_payments(self, order_id: str) -> list[dict]:
        self.call_log.append(("order_payments", {"order_id": order_id}))
        return [p for p in self._payments.values()
                if p.get("order_id") == order_id]

    def debit(self, order: dict, cid: str, vpa: str = "success@razorpay") -> dict:
        self.call_log.append(("debit", {"order_id": order["id"], "cid": cid, "vpa": vpa}))

        if self.fault == "timeout":
            import httpx
            raise httpx.TimeoutException("Fake timeout")

        if vpa == "failure@razorpay":
            raise PaymentFailed("Payment declined")

        pid = f"pay_H{self._next_pay_id:04d}"
        self._next_pay_id += 1
        payment = {"id": pid, "order_id": order["id"], "amount": order["amount"],
                   "currency": "INR", "status": "captured", "method": "upi",
                   "notes": {"challenge_id": cid}}
        self._payments[pid] = payment
        order["status"] = "paid"
        return payment

    def list_refunds(self, payment_id: str) -> list[dict]:
        self.call_log.append(("list_refunds", {"payment_id": payment_id}))
        return self._refunds.get(payment_id, [])

    def refund(self, payment_id: str, paise: int, cid: str) -> dict:
        self.call_log.append(("refund", {"payment_id": payment_id,
                                         "paise": paise, "cid": cid}))

        if self.fault == "refund_timeout":
            import httpx
            raise httpx.TimeoutException("Fake refund timeout")

        # Check for existing refund with same challenge_id
        existing = self._refunds.get(payment_id, [])
        for r in existing:
            if (r.get("notes") or {}).get("challenge_id") == cid:
                return r

        rid = f"rfnd_H{self._next_rfnd_id:04d}"
        self._next_rfnd_id += 1
        refund_obj = {"id": rid, "payment_id": payment_id, "amount": paise,
                      "currency": "INR", "status": "processed",
                      "notes": {"challenge_id": cid}}
        self._refunds.setdefault(payment_id, []).append(refund_obj)
        return refund_obj

    def seed_refund(self, payment_id: str, cid: str, refund_id: str = "rfnd_Hpre"):
        """Pre-seed a refund for convergence testing."""
        refund_obj = {"id": refund_id, "payment_id": payment_id, "amount": 500,
                      "currency": "INR", "status": "processed",
                      "notes": {"challenge_id": cid}}
        self._refunds.setdefault(payment_id, []).append(refund_obj)


# --- Fixtures ---

@pytest.fixture
def fake_clock():
    clock = FakeClock()
    set_clock(clock)
    yield clock
    reset_clock()


@pytest.fixture
def fake_rzp():
    return FakeRazorpay()


@pytest.fixture
def tmp_db(tmp_path):
    """Fresh database file per test."""
    db_path = str(tmp_path / "test.db")
    os.environ["DB_PATH"] = db_path

    from state.db import set_db_path
    set_db_path(db_path)

    from state.ledger import init_db
    init_db(db_path)

    # Seed mandates
    from state.db import get_connection
    from core.catalog import AGENT_POLICY
    conn = get_connection(db_path)
    for kid, policy in AGENT_POLICY.items():
        conn.execute(
            "INSERT OR REPLACE INTO mandates (token, agent_kid, blocked_paise, debited_paise) "
            "VALUES (?, ?, ?, 0)",
            (policy["mandate_token"], kid, policy["mandate_blocked_paise"])
        )
    conn.commit()

    yield db_path

    from state.db import close_connection
    close_connection(db_path)


@pytest.fixture
def keys():
    """Generate fresh signing keys."""
    gw_sk = Ed25519PrivateKey.generate()
    agent_a_sk = Ed25519PrivateKey.generate()
    agent_b_sk = Ed25519PrivateKey.generate()

    # Set env vars
    os.environ["GW_SK_HEX"] = gw_sk.private_bytes_raw().hex()
    os.environ["AGENT_A_SK_HEX"] = agent_a_sk.private_bytes_raw().hex()
    os.environ["AGENT_B_SK_HEX"] = agent_b_sk.private_bytes_raw().hex()
    os.environ["RZP_MODE"] = "harness"

    return {
        "gateway": {"sk": gw_sk, "pk": gw_sk.public_key()},
        "agt_coding_01": {"sk": agent_a_sk, "pk": agent_a_sk.public_key()},
        "agt_coding_02": {"sk": agent_b_sk, "pk": agent_b_sk.public_key()},
    }


@pytest.fixture
def conn(tmp_db):
    """Get a database connection for the temp DB."""
    from state.db import get_connection
    return get_connection(tmp_db)


@pytest.fixture
def client(tmp_db, keys):
    """FastAPI TestClient with harness mode."""
    os.environ["UPSTREAM_URL"] = "http://127.0.0.1:9000"
    os.environ["RZP_MODE"] = "harness"

    from fastapi.testclient import TestClient
    from gateway.app import app, _adapter
    import gateway.app as gw_module

    # Reset adapter
    gw_module._adapter = None

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
