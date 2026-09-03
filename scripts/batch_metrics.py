"""scripts/batch_metrics.py — Simulated batch metrics for merchant revenue comparison."""
import sys
import os
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.catalog import CATALOG

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def main():
    random.seed(42)  # Fixed seed for reproducibility

    # Import prices from catalog (single source)
    query_price = CATALOG["qdrant-vector-query"]["price_paise"]
    pass_price = CATALOG["day-pass"]["price_paise"]
    pass_threshold = CATALOG["day-pass"]["offer_after_paid_calls"]
    break_even = CATALOG["day-pass"]["specs"]["break_even_calls"]
    daily_pool = 15_000  # from AGENT_POLICY, ₹150

    num_agents = 30
    workloads = [random.randint(5, 40) for _ in range(num_agents)]

    # Scenario 1: Subscription-only baseline
    sub_revenue = 0
    sub_completed = 0
    sub_refunds = 0

    # Scenario 2: Per-call only
    pc_revenue = 0
    pc_completed = 0
    pc_refunds = 0

    # Scenario 3: Per-call + day pass
    pp_revenue = 0
    pp_completed = 0
    pp_refunds = 0

    for workload in workloads:
        # Scenario 1: No subscription available → zero revenue
        # Agent cannot subscribe (no card, no approval)

        # Scenario 2: Per-call only
        cost = workload * query_price
        if cost <= daily_pool:
            pc_revenue += cost
            pc_completed += 1
        else:
            # Agent abandons when projected total exceeds pool
            affordable_calls = daily_pool // query_price
            pc_revenue += affordable_calls * query_price
            # Task incomplete — not counted

        # Scenario 3: Per-call + day pass
        total_cost = 0
        paid_calls = 0
        has_pass = False

        for q in range(workload):
            if has_pass:
                # Free under pass
                continue

            call_cost = query_price
            remaining_queries = workload - q - 1
            projected_remaining = remaining_queries * query_price

            # Check if pass is offered and worth it
            if paid_calls >= pass_threshold and projected_remaining > pass_price:
                # Take the pass
                total_cost += pass_price
                has_pass = True
                pp_revenue += pass_price
            else:
                # Regular per-call
                if total_cost + call_cost <= daily_pool:
                    total_cost += call_cost
                    paid_calls += 1
                    pp_revenue += call_cost
                else:
                    break  # Abandoned

        if total_cost <= daily_pool:
            pp_completed += 1

    # Print table
    print()
    print("=" * 85)
    print("RAZOR402 MERCHANT REVENUE COMPARISON")
    print("=" * 85)
    print()
    print(f"{'Metric':<35} {'Subscription':>15} {'Per-call':>15} {'Per-call+Pass':>15}")
    print("-" * 85)
    print(f"{'Total merchant revenue':.<35} {'₹0.00':>15} "
          f"{'₹'+f'{pc_revenue/100:.2f}':>15} "
          f"{'₹'+f'{pp_revenue/100:.2f}':>15}")
    print(f"{'Tasks completed':.<35} {sub_completed:>15} "
          f"{pc_completed:>15} {pp_completed:>15}")
    print(f"{'Agent cost / completed task':.<35} {'N/A':>15} "
          f"{'₹'+f'{pc_revenue/100/max(pc_completed,1):.2f}':>15} "
          f"{'₹'+f'{pp_revenue/100/max(pp_completed,1):.2f}':>15}")
    print(f"{'Refunds issued':.<35} {sub_refunds:>15} "
          f"{pc_refunds:>15} {pp_refunds:>15}")
    print("-" * 85)
    print()
    print("Simulated traffic. Assumptions: 30 synthetic agents, workload 5–40 queries,")
    print("abandonment when projected cost exceeds budget.")
    print()

    # Summary
    if pp_revenue > pc_revenue:
        improvement = ((pp_revenue - pc_revenue) / max(pc_revenue, 1)) * 100
        print(f"Day pass improves merchant revenue by {improvement:.0f}%")
    print(f"Completed task rate: {sub_completed}/{num_agents} (sub) → "
          f"{pc_completed}/{num_agents} (per-call) → "
          f"{pp_completed}/{num_agents} (per-call+pass)")


if __name__ == "__main__":
    main()
