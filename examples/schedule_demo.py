"""Demonstrate the scheduler.

Part 1 runs the real pipeline: visibility engine -> opportunities -> greedy
schedule, over the bundled ISS element set and the station registry.

Part 2 builds a small synthetic scenario where two satellites contend for the
same antenna at the same time, to show priority resolving the conflict (a single
satellite over the registry can't create cross-satellite antenna contention).

Run from the project root:
    PYTHONPATH=src python3 examples/schedule_demo.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from orchestrator import (
    GroundStation,
    compute_all_opportunities,
    load_satellites_from_file,
    schedule_greedy,
)
from orchestrator.domain import ContactWindow

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
EPOCH = datetime(2025, 11, 4, 12, 0, tzinfo=timezone.utc)

# A simple cost model: pay per contact by provider. Owned antennas are free.
PROVIDER_COSTS = {
    "owned": 0.0,
    "ksat": 0.30,
    "aws-ground-station": 0.25,
    "leaf-space": 0.20,
}


def load_stations() -> list[GroundStation]:
    with open(os.path.join(DATA, "stations.json")) as fh:
        return [GroundStation(**row) for row in json.load(fh)]


def part1_real_pipeline() -> None:
    print("== Part 1: real ISS opportunities, scheduled ==")
    stations = load_stations()
    iss = load_satellites_from_file(os.path.join(DATA, "sample_tle.txt"))
    opps = compute_all_opportunities(iss, stations, EPOCH, EPOCH + timedelta(hours=48))

    plan = schedule_greedy(
        opps,
        stations,
        priorities={"ISS (ZARYA)": 1.0},
        provider_costs=PROVIDER_COSTS,
        max_contacts_per_satellite=8,
    )

    print(f"opportunities : {len(opps)}")
    print(f"scheduled     : {plan.scheduled_count}")
    print(f"dropped       : {plan.dropped_count}")
    print(f"total value   : {plan.total_value:.2f}")
    print(f"by provider   : {plan.contacts_by_provider()}")
    print("scheduled contacts:")
    for c in plan.scheduled:
        print(f"   [{c.provider:<18}] {c.window}")
    print()


def _win(sat, station, start_min, dur_min, peak):
    aos = EPOCH + timedelta(minutes=start_min)
    los = aos + timedelta(minutes=dur_min)
    return ContactWindow(
        satellite=sat,
        station=station,
        aos=aos,
        tca=aos + timedelta(minutes=dur_min / 2),
        los=los,
        peak_elevation_deg=peak,
        aos_azimuth_deg=0.0,
        los_azimuth_deg=180.0,
        duration_s=dur_min * 60.0,
    )


def part2_contention() -> None:
    print("== Part 2: two satellites contend for one antenna ==")
    stations = [GroundStation("GW-1", 0.0, 0.0, provider="owned")]
    opps = [
        _win("SAT-ROUTINE", "GW-1", 0, 8, peak=70.0),   # great pass, low priority
        _win("SAT-URGENT", "GW-1", 2, 8, peak=25.0),    # poor pass, high priority
    ]
    print("Both want GW-1 in overlapping windows. SAT-URGENT has priority 5x.")
    plan = schedule_greedy(
        opps, stations, priorities={"SAT-URGENT": 5.0, "SAT-ROUTINE": 1.0}
    )
    for c in plan.scheduled:
        print(f"   SCHEDULED  {c.window}")
    for w in plan.dropped:
        print(f"   DROPPED    {w}")
    print()


if __name__ == "__main__":
    part1_real_pipeline()
    part2_contention()
