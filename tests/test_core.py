"""tests/test_core.py — T01-T08: Core module tests."""
import json
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.crypto import sign_jws, verify_jws, kid_of, hmac_sha256_hex, constant_time_eq, b64u, b64ud
from core.canonical import jcs, resource_hash
from core.money import rupees


# T01
def test_jws_roundtrip():
    """sign → verify returns identical payload"""
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()
    payload = {"sub": "test", "amount": 500, "nested": {"key": "value"}}
    token = sign_jws(payload, sk, "test_kid")
    result = verify_jws(token, {"test_kid": pk})
    assert result == payload


# T02
def test_jws_rejects_alg_none():
    """alg:'none', empty sig → raises"""
    # Craft a token with alg:none
    import base64
    header = b64u(json.dumps({"alg": "none", "typ": "JWT", "kid": "x"}).encode())
    payload = b64u(json.dumps({"test": True}).encode())
    token = f"{header}.{payload}."

    sk = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="Unsupported alg"):
        verify_jws(token, {"x": sk.public_key()})


# T03
def test_jws_rejects_unknown_kid_before_verify():
    """unknown kid rejected without touching signature"""
    sk = Ed25519PrivateKey.generate()
    token = sign_jws({"test": True}, sk, "known_kid")

    # Only provide a different kid
    other_sk = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError, match="Unknown kid"):
        verify_jws(token, {"other_kid": other_sk.public_key()})


# T04
def test_jws_rejects_tampered_payload():
    """valid sig + swapped payload → raises"""
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()

    token = sign_jws({"amount": 500}, sk, "kid1")
    parts = token.split(".")

    # Swap payload
    new_payload = b64u(json.dumps({"amount": 999}).encode())
    tampered = f"{parts[0]}.{new_payload}.{parts[2]}"

    with pytest.raises(ValueError, match="Signature verification failed"):
        verify_jws(tampered, {"kid1": pk})


# T05
def test_resource_hash_query_order_invariant():
    """?a=1&b=2 ≡ ?b=2&a=1"""
    h1 = resource_hash("POST", "/provision/test", "a=1&b=2")
    h2 = resource_hash("POST", "/provision/test", "b=2&a=1")
    assert h1 == h2


# T06
def test_resource_hash_body_sensitive():
    """different body → different hash"""
    h1 = resource_hash("POST", "/provision/test", "", b"body1")
    h2 = resource_hash("POST", "/provision/test", "", b"body2")
    assert h1 != h2


# T07
def test_jcs_is_stable():
    """key order irrelevant, output byte-stable"""
    obj1 = {"b": 2, "a": 1, "c": {"z": 26, "a": 1}}
    obj2 = {"a": 1, "c": {"a": 1, "z": 26}, "b": 2}
    assert jcs(obj1) == jcs(obj2)
    # Ensure it's compact
    result = jcs(obj1)
    assert " " not in result
    assert "\n" not in result


# T08
def test_hmac_over_raw_bytes_not_reserialized():
    """irregular-spacing body verifies; re-serialized fails"""
    secret = "test_secret"
    raw_body = b'{"key" :  "value",  "num": 1}'
    mac = hmac_sha256_hex(secret, raw_body)

    # Same raw bytes verify
    assert constant_time_eq(mac, hmac_sha256_hex(secret, raw_body))

    # Re-serialized does NOT verify
    reserialized = json.dumps(json.loads(raw_body)).encode()
    mac2 = hmac_sha256_hex(secret, reserialized)
    assert not constant_time_eq(mac, mac2)


# Bonus: money formatting
def test_rupees_formatting():
    assert rupees(500) == "₹5.00"
    assert rupees(4900) == "₹49.00"
    assert rupees(15000) == "₹150.00"
    assert rupees(0) == "₹0.00"
    assert rupees(1) == "₹0.01"
