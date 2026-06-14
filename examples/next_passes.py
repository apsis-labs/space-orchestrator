"""Compute and print upcoming ISS passes over the station registry.

Run from the project root:
    PYTHONPATH=src python3 examples/next_passes.py

By default this uses the bundled TLE (so it runs with no network) and computes
passes in a 48h window starting at that TLE's epoch -- which keeps the SGP4
propagation accurate, since the geometry is valid near epoch.

To get *current* passes you can verify against https://www.n2yo.com, flip
USE_LIVE = True below and run in an environment with network access to
celestrak.org. That fetches today's elements and computes passes from now.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from orchestrator import (
    GroundStation,
    compute_passes,
    load_satellites_from_celestrak,
    load_satellites_from_file,
)

USE_LIVE = False  # set True in your own env to fetch current elements

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")

# Epoch of the bundled ISS TLE (2025-308.358 -> 2025-11-04 08:35 UTC).
BUNDLED_EPOCH = datetime(2025, 11, 4, 12, 0, tzinfo=timezone.utc)


def load_stations() -> list[GroundStation]:
    with open(os.path.join(DATA, "stations.json")) as fh:
        return [GroundStation(**row) for row in json.load(fh)]


def main() -> None:
    stations = load_stations()

    if USE_LIVE:
        iss = load_satellites_from_celestrak(catnr=25544)[0]
        start = datetime.now(timezone.utc)
    else:
        iss = load_satellites_from_file(os.path.join(DATA, "sample_tle.txt"))[0]
        start = BUNDLED_EPOCH
    end = start + timedelta(hours=48)

    print(f"Satellite : {iss.name}")
    print(f"Window    : {start:%Y-%m-%d %H:%M}Z  ->  {end:%Y-%m-%d %H:%M}Z\n")

    total = 0
    for station in stations:
        passes = compute_passes(iss, station, start, end)
        print(f"== {station.name} ({station.provider}, mask {station.min_elevation_deg:.0f}deg) "
              f"-- {len(passes)} pass(es)")
        for w in passes:
            print(f"   {w}")
        total += len(passes)
        print()

    print(f"Total opportunities in window: {total}")


if __name__ == "__main__":
    main()
