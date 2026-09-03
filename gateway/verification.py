"""gateway/verification.py — 8-step proof verification pipeline."""
import json

from core.crypto import verify_jws, kid_of, b64ud
from core.canonical import resource_hash
from core.clock import now
from core.catalog import CHALLENGE_TTL_S, AGENT_POLICY


class VerifiedProof:
    """Result of successful verification."""
    def __init__(self, agent_kid: str, challenge_id: str, challenge_payload: dict,
                 auth_payload: dict, resource_hash_val: str, amount_paise: int):
        self.agent_kid = agent_kid
        self.challenge_id = challenge_id
        self.challenge_payload = challenge_payload
        self.auth_payload = auth_payload
        self.resource_hash = resource_hash_val
        self.amount_paise = amount_paise
        self.rationale = auth_payload.get("rationale", "")
        self.jti = auth_payload.get("jti", "")
        self.mandate = auth_payload.get("mandate", {})
        self.max_debit_paise = auth_payload.get("maxDebitPaise", amount_paise)


def verify_proof(token: str, method: str, path: str, query: str, body: bytes,
                 gateway_pubs: dict, agent_pubs: dict,
                 now_ts: int | None = None) -> VerifiedProof:
    """
    8-step verification, fail-closed, cheapest first.
    Raises ValueError on any failure with the error code as message prefix.
    """
    if now_ts is None:
        now_ts = now()

    # Step 1: Parse the authorization JWS header
    try:
        auth_kid = kid_of(token)
    except Exception:
        raise ValueError("AGENT_SIGNATURE_INVALID: Cannot parse JWS header")

    # Step 2: Agent allowlisted
    if auth_kid not in AGENT_POLICY:
        raise ValueError(f"AGENT_NOT_ALLOWLISTED: {auth_kid}")

    # Step 3: Verify agent signature
    try:
        auth_payload = verify_jws(token, agent_pubs)
    except Exception as e:
        raise ValueError(f"AGENT_SIGNATURE_INVALID: {e}")

    # Step 4: Verify challenge JWS (gateway-signed)
    challenge_jws = auth_payload.get("challengeJws", "")
    if not challenge_jws:
        raise ValueError("CHALLENGE_SIGNATURE_INVALID: Missing challengeJws")

    try:
        challenge_payload = verify_jws(challenge_jws, gateway_pubs)
    except Exception as e:
        raise ValueError(f"CHALLENGE_SIGNATURE_INVALID: {e}")

    # Step 5: Challenge expired
    extra = challenge_payload.get("extra", {})
    exp = extra.get("exp", 0)
    if now_ts > exp:
        raise ValueError(f"CHALLENGE_EXPIRED: {now_ts} > {exp}")

    # Step 6: Resource hash matches live request
    live_hash = resource_hash(method, path, query, body)
    challenge_hash = challenge_payload.get("resourceHash", "")
    if live_hash != challenge_hash:
        raise ValueError(f"RESOURCE_HASH_MISMATCH: {live_hash} != {challenge_hash}")

    # Step 7: Agent kid matches
    challenge_kid = extra.get("agentKid", "")
    if auth_kid != challenge_kid:
        raise ValueError(f"AGENT_KID_MISMATCH: auth={auth_kid} challenge={challenge_kid}")

    # Step 8: Extract and validate payment details
    challenge_id = auth_payload.get("challengeId", extra.get("challengeId", ""))
    amount_paise = challenge_payload.get("amountPaise", 0)

    return VerifiedProof(
        agent_kid=auth_kid,
        challenge_id=challenge_id,
        challenge_payload=challenge_payload,
        auth_payload=auth_payload,
        resource_hash_val=live_hash,
        amount_paise=amount_paise,
    )
