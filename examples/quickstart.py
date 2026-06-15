#!/usr/bin/env python3
"""Quickstart example: compute ISS passes and schedule contacts.

This minimal example shows the core workflow:
1. Load TLE data for satellites
2. Compute visibility windows over ground stations
3. Schedule contacts (avoiding conflicts)
4. Run reconciliation with a mock provider
5. Check if we met our SLO

Run with: python examples/quickstart.py
"""

from datetime import datetime, timedelta, timezone
from orchestrator import (
    GroundStation,
    MockProviderAdapter,
    Reconciler,
    load_satellites_from_file,
    schedule_greedy,
    compute_metrics,
)
from orchestrator.visibility import compute_all_opportunities

# 1. Define ground stations
stations = [
    GroundStation("SVALBARD", 78.2, 15.4, provider="ksat"),
    GroundStation("FAIRBANKS", 64.8, -147.7, provider="aws"),
]

# 2. Load satellite TLEs (bundled ISS data)
satellites = load_satellites_from_file("data/sample_tle.txt")

# 3. Compute passes over the next 12 hours
now = datetime.now(timezone.utc)
opportunities = compute_all_opportunities(
    satellites, stations, now, now + timedelta(hours=12)
)
print(f"Found {len(opportunities)} visibility windows")

# 4. Schedule contacts (greedy algorithm avoids conflicts)
plan = schedule_greedy(opportunities, stations)
print(f"Scheduled {plan.scheduled_count} contacts, dropped {plan.dropped_count}")

if plan.scheduled_count == 0:
    print("No contacts to schedule (depends on current ISS position)")
    exit(0)

# 5. Run reconciliation with mock providers
adapters = {
    "ksat": MockProviderAdapter("ksat", failure_rate=0.2, seed=42),
    "aws": MockProviderAdapter("aws", failure_rate=0.1, seed=42),
}

reconciler = Reconciler(
    adapters=adapters,
    stations=stations,
    opportunities=opportunities,
    slo_target=0.95,
)
report = reconciler.run(plan)

# 6. Check results
metrics = compute_metrics(report)
print(f"\nResults:")
print(f"  Yield: {metrics.achieved_yield:.1%}")
print(f"  SLO met: {'Yes' if report.slo_met else 'No'}")
print(f"  Recoveries needed: {metrics.recoveries_booked}")
