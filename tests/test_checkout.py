"""tests/test_checkout.py — Test Razorpay Standard Web Checkout integration."""
import hmac
import hashlib
import os
import pytest
from fastapi.testclient import TestClient

from gateway.app import app


@pytest.fixture
def checkout_client(tmp_db, keys):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_checkout_page_serves_html(checkout_client):
    """GET /checkout serves 200 and loads Razorpay checkout script."""
    resp = checkout_client.get("/checkout")
    assert resp.status_code == 200
    assert "https://checkout.razorpay.com/v1/checkout.js" in resp.text
    assert "Razorpay Standard Checkout" in resp.text or "Standard Checkout" in resp.text


def test_checkout_config_exposes_no_secret(checkout_client):
    """GET /api/checkout-config returns key_id only, never key_secret."""
    resp = checkout_client.get("/api/checkout-config")
    assert resp.status_code == 200
    data = resp.json()
    assert "key_id" in data
    assert "key_secret" not in data
    assert "secret" not in str(data).lower() or data.get("key_id")


def test_create_order_validates_minimum_amount(checkout_client):
    """Amount < 100 paise (₹1) returns 400."""
    resp = checkout_client.post("/api/create-order", json={"amount": 50})
    assert resp.status_code == 400
    assert "Minimum amount" in resp.json().get("detail", "")


def test_create_order_validates_missing_amount(checkout_client):
    """Missing amount field returns 400."""
    resp = checkout_client.post("/api/create-order", json={})
    assert resp.status_code == 400


def test_create_order_success(checkout_client):
    """POST /api/create-order returns order_id, amount, currency, key_id."""
    resp = checkout_client.post("/api/create-order", json={
        "amount": 500,
        "currency": "INR",
        "receipt": "test_receipt_001",
        "item_id": "deepseek-v3-tokens",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "order_id" in data
    assert data["amount"] == 500
    assert data["currency"] == "INR"
    assert "key_id" in data


def test_verify_payment_signature_success(checkout_client):
    """Valid HMAC signature returns 200 with verified: True."""
    order_id = "order_test_12345"
    payment_id = "pay_test_67890"
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET") or os.environ.get("RZP_KEY_SECRET", "")

    # Generate genuine HMAC signature
    message = f"{order_id}|{payment_id}"
    sig = hmac.new(
        key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    resp = checkout_client.post("/api/verify-payment", json={
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": sig,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is True
    assert data["payment_id"] == payment_id
    assert data["order_id"] == order_id


def test_verify_payment_signature_mismatch(checkout_client):
    """Signature mismatch returns 400 and does NOT verify."""
    resp = checkout_client.post("/api/verify-payment", json={
        "razorpay_order_id": "order_test_12345",
        "razorpay_payment_id": "pay_test_67890",
        "razorpay_signature": "invalid_tampered_signature_hex",
    })
    assert resp.status_code == 400
    data = resp.json()
    assert data["verified"] is False
    assert data["error"] == "SIGNATURE_MISMATCH"


def test_verify_payment_missing_fields(checkout_client):
    """Missing fields in verify payload returns 400."""
    resp = checkout_client.post("/api/verify-payment", json={
        "razorpay_order_id": "order_test_12345",
    })
    assert resp.status_code == 400
