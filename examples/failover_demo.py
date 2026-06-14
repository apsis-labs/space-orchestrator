"""End-to-end failover demo.

Pipeline: visibility -> schedule -> reconcile, on the bundled ISS data.

A Leaf Space outage takes down Punta Arenas during the evening, which is exactly
when the scheduler placed its best (near-overhead) contacts. Watch the reconciler
detect the failures and re-book the lost downlinks onto later opportunities,
then report achieved yield against the SLO.

Run from the project root:
    PYTHONPATH=src python3 examples/failover_demo.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from orchestrator import (
    GroundStation,
    MockProviderAdapter,
    Reconciler,
    compute_all_opportunities,
    load_satellites_from_file,
    schedule_greedy,
)

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
EPOCH = datetime(2025, 11, 4, 12, 0, tzinfo=timezone.utc)

PROVIDER_COSTS = {"owned": 0.0, "ksat": 0.30, "aws-ground-station": 0.25, "leaf-space": 0.20}


def load_stations() -> list[GroundStation]:
    with open(os.path.join(DATA, "stations.json")) as fh:
        return [GroundStation(**row) for row in json.load(fh)]


def main() -> None:
    stations = load_stations()
    iss = load_satellites_from_file(os.path.join(DATA, "sample_tle.txt"))
    opps = compute_all_opportunities(iss, stations, EPOCH, EPOCH + timedelta(hours=48))

    plan = schedule_greedy(
        opps, stations,
        priorities={"ISS (ZARYA)": 1.0},
        provider_costs=PROVIDER_COSTS,
        max_contacts_per_satellite=8,
    )

    # Leaf Space (Punta Arenas) goes dark 17:00-20:00 UTC on day one -- right over
    # the two best evening passes the scheduler chose.
    outage_start = datetime(2025, 11, 4, 17, 0, tzinfo=timezone.utc)
    outage_end = datetime(2025, 11, 4, 20, 0, tzinfo=timezone.utc)
    adapters = {
        "owned": MockProviderAdapter("owned", failure_rate=0.0, seed=1),
        "ksat": MockProviderAdapter("ksat", failure_rate=0.05, seed=2),
        "aws-ground-station": MockProviderAdapter("aws-ground-station", failure_rate=0.05, seed=3),
        "leaf-space": MockProviderAdapter(
            "leaf-space", failure_rate=0.05, seed=4,
            outages=[("PUNTA-ARENAS", outage_start, outage_end)],
        ),
    }

    report = Reconciler(
        adapters, stations, opps,
        priorities={"ISS (ZARYA)": 1.0},
        provider_costs=PROVIDER_COSTS,
        slo_target=0.95,
    ).run(plan)

    print("== Timeline (book -> outcome, with recoveries) ==")
    for a in report.timeline():
        tag = "RECOVERY" if a.attempt > 0 else "planned "
        mark = "OK  " if a.state.value == "succeeded" else "FAIL"
        line = (f"  [{tag}] {mark} {a.window.satellite:<12} @ {a.window.station:<12} "
                f"{a.window.aos:%m-%d %H:%M}Z via {a.provider:<18} {a.detail}")
        print(line)
        if a.recovers is not None:
            print(f"           ^ recovers failed {a.recovers.station} "
                  f"{a.recovers.aos:%m-%d %H:%M}Z")

    print("\n== Reliability report ==")
    print(f"  planned contacts   : {report.planned}")
    print(f"  satisfied          : {report.satisfied}")
    print(f"  recovered          : {report.recovered_demands}")
    print(f"  unrecovered        : {report.unrecovered}")
    print(f"  recoveries booked  : {report.recoveries_booked}")
    print(f"  achieved yield     : {report.achieved_yield:.1%}")
    print(f"  SLO target         : {report.slo_target:.0%}  "
          f"(error budget: {report.error_budget} unrecovered allowed)")
    print(f"  SLO met            : {'YES' if report.slo_met else 'NO'}")


if __name__ == "__main__":
    main()
