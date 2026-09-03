"""agent/transport.py — HTTP transport with 402 handling."""
import json
import secrets
import httpx

from core.crypto import sign_jws, verify_jws, b64u
from core.catalog import AGENT_POLICY
from agent.wallet import AgentWallet


class Razor402Transport:
    """
    HTTP client that handles 402 challenges automatically.
    Injects X-Razor402-Agent header.
    On 402: parse accepts, select option, sign authorization, retry.
    """

    def __init__(self, wallet: AgentWallet, gateway_url: str = "http://127.0.0.1:8000",
                 skip_advisory: bool = False):
        self.wallet = wallet
        self.gateway_url = gateway_url
        self.skip_advisory = skip_advisory
        self.client = httpx.Client(timeout=30.0)

    def procure(self, item_id: str, rationale: str,
                select_index: int = 0) -> dict:
        """
        Purchase an item. Handles 402 flow automatically.
        Returns the response body or error.
        """
        url = f"{self.gateway_url}/provision/{item_id}"

        # Initial request (will get 402)
        resp = self.client.post(
            url,
            headers={"X-Razor402-Agent": self.wallet.kid},
        )

        if resp.status_code == 200:
            # Already covered (e.g. day pass)
            return {"status": "pass_covered", "body": resp.json(),
                    "headers": dict(resp.headers)}

        if resp.status_code != 402:
            return {"status": "error", "code": resp.status_code,
                    "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text}

        # Parse 402 challenge
        challenge_body = resp.json()
        accepts = challenge_body.get("accepts", [])

        if not accepts:
            return {"status": "error", "detail": "No accepts in 402"}

        # Select option
        idx = min(select_index, len(accepts) - 1)
        selected = accepts[idx]
        amount = selected["amountPaise"]

        # Get the challenge JWS
        jws_list = challenge_body.get("challengeJwsList", [])
        if jws_list:
            challenge_jws = jws_list[idx]
        else:
            challenge_jws = challenge_body.get("challengeJws", "")

        challenge_id = selected["extra"]["challengeId"]

        # Advisory check (unless skipped)
        if not self.skip_advisory:
            from policy.guardrails import evaluate
            from core.clock import now
            verdict = evaluate(
                self.wallet.kid, item_id, amount,
                selected.get("payTo", "acc_buildbroker_test"),
                self.wallet.captured_paise, self.wallet.per_call_cap_paise,
                self.wallet.daily_pool_paise, now(),
            )
            if not verdict.allowed:
                return {"status": "advisory_denied", "code": verdict.code,
                        "detail": verdict.detail}

        # Local hold
        if not self.wallet.hold(amount):
            return {"status": "budget_exceeded",
                    "detail": f"Local budget insufficient: {self.wallet.remaining_paise()} < {amount}"}

        # Build and sign authorization
        jti = b64u(secrets.token_bytes(16))
        from core.clock import now
        auth_payload = {
            "typ": "razor402.payment-authorization+jws",
            "challengeJws": challenge_jws,
            "challengeId": challenge_id,
            "agentKid": self.wallet.kid,
            "mandate": {"type": "upi_sbmd", "token": self.wallet.mandate_token},
            "maxDebitPaise": amount,
            "rationale": rationale[:500],  # ≤500 chars
            "jti": jti,
            "iat": now(),
        }

        token = sign_jws(auth_payload, self.wallet.sk, self.wallet.kid)

        # Retry with payment
        resp2 = self.client.post(
            url,
            headers={
                "X-PAYMENT": token,
                "X-Razor402-Agent": self.wallet.kid,
            },
        )

        if resp2.status_code == 200:
            self.wallet.capture(amount)
            payment_resp = resp2.headers.get("X-PAYMENT-RESPONSE", "{}")
            return {
                "status": "fulfilled",
                "body": resp2.json(),
                "payment": json.loads(payment_resp),
                "amount_paise": amount,
            }

        if resp2.status_code == 502:
            # Compensation — release hold
            self.wallet.release(amount)
            return {
                "status": "compensated",
                "body": resp2.json(),
                "amount_paise": amount,
            }

        if resp2.status_code == 202:
            # In-doubt
            return {
                "status": "in_doubt",
                "retry_after": resp2.headers.get("Retry-After", "15"),
            }

        if resp2.status_code == 409:
            body = resp2.json()
            if body.get("error") == "IN_FLIGHT":
                # Retry
                import time
                retry_after = int(resp2.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                return self.procure(item_id, rationale, select_index)

            self.wallet.release(amount)
            return {"status": "conflict", "body": body}

        # Other errors (403, etc)
        self.wallet.release(amount)
        return {
            "status": "denied",
            "code": resp2.status_code,
            "body": resp2.json() if resp2.headers.get("content-type", "").startswith("application/json") else resp2.text,
        }

    def discover(self) -> dict:
        """Get the catalog."""
        resp = self.client.get(f"{self.gateway_url}/.well-known/agent-catalog")
        return resp.json()

    def close(self):
        self.client.close()
