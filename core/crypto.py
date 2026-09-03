"""core/crypto.py — Ed25519 JWS (pinned header), HMAC utilities."""
import base64
import json
import hmac
import hashlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def b64u(b: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64ud(s: str) -> bytes:
    """Base64url decode with padding restoration."""
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def sign_jws(payload: dict, sk: Ed25519PrivateKey, kid: str) -> str:
    """Create a compact JWS with EdDSA, typ=JWT, and the given kid."""
    header = {"alg": "EdDSA", "typ": "JWT", "kid": kid}
    h = b64u(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    p = b64u(json.dumps(payload, separators=(",", ":"), sort_keys=False).encode())
    signing_input = f"{h}.{p}".encode("ascii")
    sig = sk.sign(signing_input)
    return f"{h}.{p}.{b64u(sig)}"


def verify_jws(token: str, pubs: dict[str, Ed25519PublicKey]) -> dict:
    """
    Verify a compact JWS. Returns the parsed payload.
    Steps (fail-closed, cheapest first):
    1. Parse header; reject unless alg=="EdDSA" and typ=="JWT"
    2. Reject unknown kid BEFORE signature verify
    3. Verify signature over exact h.p bytes
    4. Parse payload ONLY after successful verify
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWS must have 3 parts")

    h_b64, p_b64, s_b64 = parts

    # Step 1: Parse header, reject bad alg/typ
    header = json.loads(b64ud(h_b64))
    if header.get("alg") != "EdDSA":
        raise ValueError(f"Unsupported alg: {header.get('alg')}")
    if header.get("typ") != "JWT":
        raise ValueError(f"Unsupported typ: {header.get('typ')}")

    # Step 2: Reject unknown kid BEFORE verify
    kid = header.get("kid")
    if kid not in pubs:
        raise ValueError(f"Unknown kid: {kid}")

    # Step 3: Verify signature
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = b64ud(s_b64)
    try:
        pubs[kid].verify(sig, signing_input)
    except Exception as e:
        raise ValueError(f"Signature verification failed: {e}") from e

    # Step 4: Parse payload only after verify
    payload = json.loads(b64ud(p_b64))
    return payload


def kid_of(token: str) -> str:
    """Extract kid from the JWS header without verifying."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("JWS must have 3 parts")
    header = json.loads(b64ud(parts[0]))
    kid = header.get("kid")
    if not kid:
        raise ValueError("No kid in JWS header")
    return kid


def hmac_sha256_hex(secret: str, raw: bytes) -> str:
    """Compute HMAC-SHA256 over raw bytes, return hex."""
    return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison."""
    return hmac.compare_digest(a, b)
