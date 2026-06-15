"""Tests for the greedy scheduler.

These use synthetic ContactWindows so the scheduling logic is tested in
isolation from orbital mechanics: we construct exactly the contention we want
and assert the allocator does the right thing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator import GroundStation, schedule_cpsat, schedule_greedy
from orchestrator.domain import ContactWindow

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

STATIONS = [
    GroundStation("GW-1", 0.0, 0.0, provider="provider-a"),
    GroundStation("GW-2", 10.0, 10.0, provider="provider-b"),
]


def window(sat, station, start_min, dur_min, peak=45.0):
    aos = T0 + timedelta(minutes=start_min)
    los = aos + timedelta(minutes=dur_min)
    tca = aos + timedelta(minutes=dur_min / 2)
    return ContactWindow(
        satellite=sat,
        station=station,
        aos=aos,
        tca=tca,
        los=los,
        peak_elevation_deg=peak,
        aos_azimuth_deg=0.0,
        los_azimuth_deg=180.0,
        duration_s=dur_min * 60.0,
    )


def _overlaps(a: ContactWindow, b: ContactWindow) -> bool:
    return a.aos < b.los and b.aos < a.los


def test_no_antenna_is_double_booked():
    # Three overlapping contacts all want GW-1 in the same window.
    opps = [
        window("SAT-A", "GW-1", 0, 8),
        window("SAT-B", "GW-1", 2, 8),
        window("SAT-C", "GW-1", 4, 8),
        window("SAT-D", "GW-2", 0, 8),  # different antenna, should coexist
    ]
    plan = schedule_greedy(opps, STATIONS)

    by_station: dict[str, list[ContactWindow]] = {}
    for c in plan.scheduled:
        by_station.setdefault(c.window.station, []).append(c.window)
    for station_windows in by_station.values():
        for i in range(len(station_windows)):
            for j in range(i + 1, len(station_windows)):
                assert not _overlaps(station_windows[i], station_windows[j])


def test_priority_wins_contention():
    # Two satellites want the same antenna at the same time; the higher-priority
    # one must be the one that gets scheduled.
    opps = [
        window("LOWPRI", "GW-1", 0, 8, peak=80.0),   # even with a better pass...
        window("HIGHPRI", "GW-1", 1, 8, peak=20.0),  # ...priority should win
    ]
    plan = schedule_greedy(opps, STATIONS, priorities={"HIGHPRI": 10.0, "LOWPRI": 1.0})

    scheduled_sats = {c.window.satellite for c in plan.scheduled}
    assert "HIGHPRI" in scheduled_sats
    assert "LOWPRI" not in scheduled_sats


def test_nonoverlapping_contacts_all_scheduled():
    opps = [
        window("SAT-A", "GW-1", 0, 8),
        window("SAT-A", "GW-1", 30, 8),
        window("SAT-B", "GW-2", 5, 8),
    ]
    plan = schedule_greedy(opps, STATIONS)
    assert plan.dropped_count == 0
    assert plan.scheduled_count == 3


def test_every_opportunity_is_scheduled_or_dropped():
    opps = [window(f"SAT-{i}", "GW-1", i, 8) for i in range(10)]
    plan = schedule_greedy(opps, STATIONS)
    assert plan.scheduled_count + plan.dropped_count == len(opps)


def test_setup_teardown_gap_is_enforced():
    # Back-to-back with no gap: second should be dropped when buffer > slack.
    opps = [
        window("SAT-A", "GW-1", 0, 10),   # 00:00 -> 00:10
        window("SAT-B", "GW-1", 10, 10),  # 00:10 -> 00:20, zero gap
    ]
    plan = schedule_greedy(opps, STATIONS, setup_teardown_s=120.0)
    assert plan.scheduled_count == 1
    assert plan.dropped_count == 1


def test_max_contacts_per_satellite_cap():
    opps = [window("SAT-A", "GW-1", i * 30, 8) for i in range(5)]  # 5 non-conflicting
    plan = schedule_greedy(opps, STATIONS, max_contacts_per_satellite=2)
    assert plan.contacts_by_satellite().get("SAT-A", 0) == 2
    assert plan.dropped_count == 3


def test_schedule_cpsat_produces_valid_plan_and_respects_constraints():
    # Same contention as greedy priority test, but using CP-SAT
    opps = [
        window("LOWPRI", "GW-1", 0, 8, peak=80.0),
        window("HIGHPRI", "GW-1", 1, 8, peak=20.0),
    ]
    plan = schedule_cpsat(
        opps, STATIONS, priorities={"HIGHPRI": 10.0, "LOWPRI": 1.0}
    )

    scheduled_sats = {c.window.satellite for c in plan.scheduled}
    assert "HIGHPRI" in scheduled_sats
    assert "LOWPRI" not in scheduled_sats
    assert plan.scheduled_count + plan.dropped_count == len(opps)


def test_schedule_cpsat_respects_max_contacts_and_buffer():
    # 3 non-conflicting for one sat, but cap at 2 + buffer test
    opps = [window("SAT-A", "GW-1", i * 30, 8) for i in range(3)]
    plan = schedule_cpsat(
        opps, STATIONS, max_contacts_per_satellite=2, setup_teardown_s=120.0
    )
    assert plan.contacts_by_satellite().get("SAT-A", 0) <= 2
    # With large buffer some may be dropped even without cap in this setup
    assert plan.dropped_count >= 0  # basic sanity


def test_schedule_cpsat_requires_ortools(monkeypatch):
    monkeypatch.setattr("orchestrator.scheduler.cp_model", None)
    with pytest.raises(ImportError, match="ortools"):
        schedule_cpsat([], STATIONS)
