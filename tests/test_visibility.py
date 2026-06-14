"""Sanity tests that lock in physical invariants of the visibility engine.

These don't check exact times (those depend on the TLE), they check that the
*physics* holds: passes are well-formed, ordered, clear the mask, and respect
orbital geometry. If a refactor breaks any of these, something is wrong.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from orchestrator import GroundStation, compute_passes, load_satellites_from_file

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
EPOCH = datetime(2025, 11, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def iss():
    return load_satellites_from_file(os.path.join(DATA, "sample_tle.txt"))[0]


def test_passes_are_wellformed_and_clear_the_mask(iss):
    station = GroundStation("BAYAREA-1", 37.6624, -121.8747, 110.0, min_elevation_deg=10.0)
    passes = compute_passes(iss, station, EPOCH, EPOCH + timedelta(hours=48))

    assert passes, "ISS should be visible from the Bay Area within 48h"
    for w in passes:
        assert w.aos < w.tca < w.los          # ordering: rise -> culminate -> set
        assert w.duration_s > 0
        assert w.peak_elevation_deg >= 10.0   # culmination clears the mask
        assert 0.0 <= w.aos_azimuth_deg <= 360.0


def test_passes_are_time_ordered(iss):
    station = GroundStation("BAYAREA-1", 37.6624, -121.8747, 110.0, min_elevation_deg=10.0)
    passes = compute_passes(iss, station, EPOCH, EPOCH + timedelta(hours=48))
    aos_times = [w.aos for w in passes]
    assert aos_times == sorted(aos_times)


def test_inclination_limits_high_latitude_visibility(iss):
    """The ISS orbits at ~51.6 deg inclination, so a station at 78 deg N
    (well inside the polar cap the ground track never reaches) should see no
    passes, while a station near the orbit's southern edge sees high ones."""
    svalbard = GroundStation("SVALBARD", 78.2297, 15.3975, 458.0, min_elevation_deg=5.0)
    punta = GroundStation("PUNTA-ARENAS", -52.9381, -70.8475, 35.0, min_elevation_deg=5.0)
    window = (EPOCH, EPOCH + timedelta(hours=48))

    assert compute_passes(iss, svalbard, *window) == []
    high = [w for w in compute_passes(iss, punta, *window) if w.peak_elevation_deg > 50.0]
    assert high, "a station under the orbit's edge should get near-overhead passes"
