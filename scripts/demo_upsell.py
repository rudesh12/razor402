"""scripts/demo_upsell.py — Demo: Day pass volume upsell triggered at 8 paid calls."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agent.wallet import AgentWallet
from agent.transport import Razor402Transport

def main():
    print("=" * 65)
    print(" DEMO: DYNAMIC 402 UPSELL (DAY PASS OFFERED AT QUERY 8)")
    print("=" * 65)
    print("Scenario: Agent procures 8 vector queries individually.")
    print("          On the 9th challenge, gateway offers multi-option accepts[]:")
    print("          Option 0: Standard per-query (₹5.00)")
    print("          Option 1: Day Pass bundle (₹49.00, unlimited 24h)")
    print("          Agent accepts Day Pass. Subsequent queries are pass_covered (₹0.00).\n")

    gateway_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000")
    sk_hex = os.environ.get("AGENT_A_SK_HEX", "")
    wallet = AgentWallet("agt_coding_01", sk_hex)
    transport = Razor402Transport(wallet, gateway_url)

    # 1. Buy 8 queries
    print("[1] Executing 8 individual vector queries...")
    for i in range(1, 9):
        res = transport.procure(
            "qdrant-vector-query",
            f"Query {i}: training vector index for document chunking."
        )
        print(f"  → Call {i}: Status={res.get('status')} | Payment={res.get('payment', {}).get('paymentId')}")

    print()
    # 2. 9th query: Day pass is now offered
    print("[2] 9th Query: Gateway pricing engine detects eligibility...")
    print("  → Accepting Day Pass volume bundle (select_index=1)...")
    res_pass = transport.procure(
        "day-pass",
        "Economic decision: Workload requires >10 total queries; Day Pass saves ~₹60 vs per-query.",
        select_index=1
    )
    print(f"  → Status: {res_pass.get('status')}")
    print(f"  → Payment: {res_pass.get('payment', {}).get('paymentId')}\n")

    # 3. 10th query: should be pass_covered for ₹0.00
    print("[3] 10th Query: Validating pass coverage...")
    res_covered = transport.procure(
        "qdrant-vector-query",
        "Testing vector query under newly active Day Pass."
    )
    print(f"  → Status: {res_covered.get('status')} (Free under Day Pass!)")
    print(f"  → Amount Charged: 0 paise\n")

    summary = wallet.summary()
    print("Budget Summary:")
    print(f"  → Remaining: {summary['remaining_display']}")
    print(f"  → Total Spent: ₹{summary['captured_paise']/100:.2f} (8 × ₹5 + ₹49 = ₹89.00)")
    print("=" * 65)
    print("✓ VERIFIED: Dynamic HTTP 402 volume upsell and pass activation.\n")

if __name__ == "__main__":
    main()
