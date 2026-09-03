"""gateway/checkout.py — Razorpay Standard Web Checkout endpoints."""
import os
import hmac
import hashlib

import razorpay
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse

router = APIRouter(prefix="/api", tags=["checkout"])

_rzp_client = None


def _get_credentials() -> tuple[str, str]:
    key_id = os.environ.get("RAZORPAY_KEY_ID") or os.environ.get("RZP_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET") or os.environ.get("RZP_KEY_SECRET", "")
    return key_id, key_secret


def _get_client() -> razorpay.Client:
    global _rzp_client
    if _rzp_client is None:
        key_id, key_secret = _get_credentials()
        if not key_id or not key_secret:
            raise HTTPException(status_code=500,
                                detail="RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set")
        _rzp_client = razorpay.Client(auth=(key_id, key_secret))
    return _rzp_client


@router.post("/create-order")
async def create_order(request: Request):
    """
    STEP 1: Create a Razorpay order.
    Request body: { amount: int (paise), currency?: str, receipt?: str, item_id?: str }
    Returns: { order_id, amount, currency, key_id }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    amount = body.get("amount")
    if amount is None:
        raise HTTPException(status_code=400, detail="Missing 'amount' field")

    try:
        amount = int(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="'amount' must be an integer (paise)")

    # Minimum 100 paise (₹1)
    if amount < 100:
        raise HTTPException(status_code=400,
                            detail=f"Minimum amount is 100 paise (₹1). Got {amount}")

    currency = body.get("currency", "INR")
    receipt = body.get("receipt", None)
    item_id = body.get("item_id", "manual-checkout")

    # Build notes for traceability
    notes = {"source": "razor402-checkout", "item_id": item_id}

    order_data = {
        "amount": amount,
        "currency": currency,
        "notes": notes,
    }
    if receipt:
        order_data["receipt"] = receipt

    try:
        client = _get_client()
        order = client.order.create(data=order_data)
    except razorpay.errors.BadRequestError as e:
        raise HTTPException(status_code=400, detail=f"Razorpay error: {e}")
    except razorpay.errors.ServerError as e:
        raise HTTPException(status_code=500, detail=f"Razorpay server error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Order creation failed: {e}")

    return {
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order["currency"],
        "key_id": _get_credentials()[0],
    }


@router.post("/verify-payment")
async def verify_payment(request: Request):
    """
    STEP 3: Verify Razorpay payment signature.
    Request body: { razorpay_order_id, razorpay_payment_id, razorpay_signature }
    Algorithm: HMAC-SHA256(order_id + "|" + payment_id, KEY_SECRET)
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    order_id = body.get("razorpay_order_id")
    payment_id = body.get("razorpay_payment_id")
    signature = body.get("razorpay_signature")

    if not all([order_id, payment_id, signature]):
        raise HTTPException(status_code=400,
                            detail="Missing required fields: razorpay_order_id, "
                                   "razorpay_payment_id, razorpay_signature")

    _, key_secret = _get_credentials()
    if not key_secret:
        raise HTTPException(status_code=500, detail="RAZORPAY_KEY_SECRET not configured")

    # HMAC-SHA256(order_id + "|" + payment_id, key_secret)
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        return JSONResponse(
            status_code=400,
            content={
                "verified": False,
                "error": "SIGNATURE_MISMATCH",
                "detail": "Payment signature verification failed. Do NOT mark as paid.",
            },
        )

    # Signature valid — optionally record in audit
    from state.db import get_connection
    from state.ledger import note
    try:
        conn = get_connection()
        note(conn, None, "CHECKOUT_PAYMENT_VERIFIED", "checkout", {
            "order_id": order_id,
            "payment_id": payment_id,
            "source": "standard_checkout",
        })
    except Exception:
        pass  # Audit is best-effort for checkout payments

    return {
        "verified": True,
        "payment_id": payment_id,
        "order_id": order_id,
    }


@router.get("/checkout-config")
async def checkout_config():
    """Return public checkout configuration (key_id only, never secret)."""
    return {
        "key_id": _get_credentials()[0],
        "currency": "INR",
        "merchant_name": "BuildBroker",
        "description": "Razor402 API Resource Purchase",
        "theme_color": "#6366f1",
    }

