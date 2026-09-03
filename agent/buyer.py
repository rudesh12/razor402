"""agent/buyer.py — AI procurement agent CLI."""
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from agent.wallet import AgentWallet
from agent.transport import Razor402Transport
from core.money import rupees

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


MISSIONS = {
    "rag": (
        "Build a RAG pipeline over a small document corpus with one market-data "
        "anchor. Your hard budget is ₹150. The vector workload is approximately "
        "20 queries. Buy only what the task needs. For every purchase, state your "
        "reasoning — it is signed and permanently audit-logged."
    ),
}


def run_replay(transport: Razor402Transport, fixture_path: str):
    """Execute a recorded fixture against the live gateway."""
    with open(fixture_path, encoding="utf-8") as f:
        fixture = json.load(f)

    print(f"[agent] Replaying fixture: {fixture_path}")
    print(f"[agent] Mission: {fixture.get('mission', 'N/A')}")
    print(f"[agent] Provider: {fixture.get('provider', 'N/A')}")
    print()

    results = []
    for i, turn in enumerate(fixture.get("turns", [])):
        tool = turn.get("tool", "")
        args = turn.get("args", {})

        if tool == "discover_catalog":
            print(f"[agent] Step {i+1}: discover_catalog()")
            catalog = transport.discover()
            print(f"  → {len(catalog.get('items', []))} items")
            results.append({"tool": tool, "result": "ok"})

        elif tool == "check_budget":
            print(f"[agent] Step {i+1}: check_budget()")
            budget = transport.wallet.summary()
            print(f"  → Remaining: {budget['remaining_display']}")
            results.append({"tool": tool, "result": budget})

        elif tool == "procure":
            item_id = args.get("item_id", "")
            rationale = args.get("rationale", "replay: no rationale recorded")
            select_index = args.get("select_index", 0)
            print(f"[agent] Step {i+1}: procure({item_id})")
            print(f"  Rationale: {rationale[:80]}...")

            result = transport.procure(item_id, rationale, select_index)
            status = result.get("status", "unknown")
            print(f"  → Status: {status}")
            if status == "fulfilled":
                print(f"  → Payment: {result.get('payment', {}).get('paymentId', 'N/A')}")
            elif status in ("denied", "advisory_denied"):
                print(f"  → Denied: {result.get('code', '')} {result.get('detail', '')}")
            results.append({"tool": tool, "item_id": item_id, "result": status})

    # Summary
    print()
    print("=" * 60)
    print(f"[agent] Replay complete. {len(results)} steps executed.")
    budget = transport.wallet.summary()
    print(f"[agent] Budget: {budget['remaining_display']} remaining "
          f"({rupees(budget['captured_paise'])} spent)")
    print("=" * 60)

    return results


def run_live(transport: Razor402Transport, mission: str):
    """Execute live autonomous procurement using Google Gemini."""
    from google import genai
    from agent.llm import SYSTEM_PROMPT
    from datetime import datetime, timezone

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[agent] Error: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    recorded_turns = []
    step_num = [0]

    import time

    def _pace():
        # Respect Gemini free-tier 5 RPM limit (1 request every 12s)
        time.sleep(12.5)

    def discover_catalog() -> dict:
        """Discover available API resources and their pricing, specs, and sellers."""
        step_num[0] += 1
        print(f"[agent] Step {step_num[0]}: discover_catalog()")
        catalog = transport.discover()
        items = catalog.get("items", [])
        print(f"  → {len(items)} items available in catalog")
        recorded_turns.append({"tool": "discover_catalog", "args": {}})
        _pace()
        return catalog

    def check_budget() -> dict:
        """Check agent wallet and remaining spending budget in paise and rupees."""
        step_num[0] += 1
        print(f"[agent] Step {step_num[0]}: check_budget()")
        summary = transport.wallet.summary()
        print(f"  → Remaining: {summary['remaining_display']}")
        recorded_turns.append({"tool": "check_budget", "args": {}})
        _pace()
        return summary

    def procure(item_id: str, rationale: str, select_index: int = 0) -> dict:
        """Procure an API resource. You MUST provide an economic rationale comparing providers."""
        step_num[0] += 1
        print(f"[agent] Step {step_num[0]}: procure({item_id})")
        print(f"  Rationale: {rationale[:80]}...")
        result = transport.procure(item_id, rationale, select_index)
        status = result.get("status", "unknown")
        print(f"  → Status: {status}")
        if status == "fulfilled":
            print(f"  → Payment: {result.get('payment', {}).get('paymentId', 'N/A')}")
        elif status in ("denied", "advisory_denied"):
            print(f"  → Denied: {result.get('code', '')} {result.get('detail', '')}")
        recorded_turns.append({
            "tool": "procure",
            "args": {"item_id": item_id, "rationale": rationale, "select_index": select_index}
        })
        _pace()
        return {
            "status": status,
            "item_id": item_id,
            "paymentId": result.get("payment", {}).get("paymentId"),
            "amountPaise": result.get("amountPaise"),
        }


    print("[agent] Connecting to Google Gemini (gemini-2.5-flash)...")
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config={
            "system_instruction": SYSTEM_PROMPT,
            "tools": [discover_catalog, check_budget, procure],
        }
    )

    prompt = (
        f"Mission: {mission}\n\n"
        f"Instructions:\n"
        f"1. Call discover_catalog() to evaluate available providers for LLM inference, vector search, and market data.\n"
        f"2. Call check_budget() to verify your funds.\n"
        f"3. Compare competing providers on price and specs, selecting the most cost-effective option for the RAG task.\n"
        f"4. Procure LLM tokens (e.g. deepseek-v4-flash or deepseek-v3-tokens).\n"
        f"5. Procure 8 vector queries, then buy the day-pass bundle to cover remaining queries at a discount.\n"
        f"6. Procure 1x market-snapshot for real-time data.\n"
        f"7. In every single procure call, provide an explicit comparison rationale.\n"
        f"8. Ensure total spend stays strictly under your ₹150 budget."
    )

    response = chat.send_message(prompt)

    print()
    print("=" * 60)
    print(f"[agent] Live execution complete. {len(recorded_turns)} steps executed.")
    budget = transport.wallet.summary()
    print(f"[agent] Budget: {budget['remaining_display']} remaining "
          f"({rupees(budget['captured_paise'])} spent)")
    print("=" * 60)
    try:
        text = getattr(response, "text", "")
        if text:
            print(f"[agent] Summary:\n{text.strip()}")
    except Exception:
        pass


    # Save recorded run to fixture
    if recorded_turns:
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "procurement_run.json")
        fixture_data = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "mission": mission,
            "turns": recorded_turns,
        }
        with open(fixture_path, "w", encoding="utf-8") as f:
            json.dump(fixture_data, f, indent=2, ensure_ascii=False)
        print(f"[agent] Recorded run saved to: {fixture_path}")

    return recorded_turns


def main():
    parser = argparse.ArgumentParser(description="Razor402 AI Procurement Agent")
    parser.add_argument("--agent", default="agt_coding_01",
                        help="Agent identity (kid)")
    parser.add_argument("--mission", default="rag",
                        help="Mission name or custom prompt")
    parser.add_argument("--replay", action="store_true",
                        help="Replay from fixture instead of live LLM")
    parser.add_argument("--live", action="store_true",
                        help="Use live LLM calls")
    parser.add_argument("--fixture", default=None,
                        help="Path to fixture JSON")
    parser.add_argument("--skip-advisory", action="store_true",
                        help="Skip advisory check (compromised client simulation)")
    parser.add_argument("--json-log", action="store_true",
                        help="Output JSON log")
    parser.add_argument("--gateway", default=None,
                        help="Gateway URL")
    args = parser.parse_args()

    # Determine keys
    key_map = {
        "agt_coding_01": "AGENT_A_SK_HEX",
        "agt_coding_02": "AGENT_B_SK_HEX",
    }
    sk_hex = os.environ.get(key_map.get(args.agent, ""), "")
    if not sk_hex:
        print(f"Error: No key found for agent {args.agent}")
        print("Run 'python scripts/keygen.py' and add keys to .env")
        sys.exit(1)

    gateway_url = args.gateway or os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000")

    wallet = AgentWallet(args.agent, sk_hex)
    transport = Razor402Transport(wallet, gateway_url, skip_advisory=args.skip_advisory)

    mission = MISSIONS.get(args.mission, args.mission)
    print(f"[agent] Identity: {args.agent}")
    print(f"[agent] Budget: {rupees(wallet.daily_pool_paise)}")
    print(f"[agent] Mission: {mission[:80]}...")
    print()

    if args.live:
        run_live(transport, mission)
    else:
        # Replay mode default
        fixture_path = args.fixture
        if not fixture_path:
            fixture_path = os.path.join(
                os.path.dirname(__file__), "fixtures", "procurement_run.json"
            )

        if not os.path.exists(fixture_path):
            print(f"Fixture not found: {fixture_path}")
            print("Creating a default fixture...")
            _create_default_fixture(fixture_path)

        run_replay(transport, fixture_path)

    transport.close()


def _create_default_fixture(path: str):
    """Create a default fixture for the RAG mission."""
    fixture = {
        "recorded_at": "2026-09-03T14:22:11Z",
        "provider": "fixture",
        "model": "default",
        "mission": MISSIONS["rag"],
        "turns": [
            {"tool": "discover_catalog", "args": {}},
            {"tool": "check_budget", "args": {}},
            {"tool": "procure", "args": {
                "item_id": "deepseek-v3-tokens",
                "rationale": "LLM inference needed to process and embed document corpus for RAG pipeline. 100k token quota sufficient for initial document processing."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Vector search query needed to test document retrieval after embedding."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Second vector query to validate retrieval quality across document sections."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Testing vector search with different query embedding for accuracy."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Vector query to benchmark recall metrics for the RAG pipeline."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Additional vector search for edge case document retrieval."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Vector query for cross-reference verification in document corpus."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Seventh vector query for comprehensive coverage testing."
            }},
            {"tool": "procure", "args": {
                "item_id": "qdrant-vector-query",
                "rationale": "Eighth vector query — threshold for day pass evaluation."
            }},
            {"tool": "procure", "args": {
                "item_id": "day-pass",
                "rationale": "Day pass is cost-effective at 8+ paid queries. Remaining ~12 queries will be free under pass, saving ₹60 vs per-call pricing.",
                "select_index": 1
            }},
            {"tool": "procure", "args": {
                "item_id": "market-snapshot",
                "rationale": "Market data snapshot needed as the real-time data anchor for the RAG pipeline."
            }},
            {"tool": "check_budget", "args": {}},
        ],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fixture, f, indent=2, ensure_ascii=False)
    print(f"  Created: {path}")


if __name__ == "__main__":
    main()

