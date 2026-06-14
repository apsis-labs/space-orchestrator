"""Tests for the reconciler / failover control loop.

Synthetic opportunities again, so we can construct exact failure scenarios and
assert the loop recovers correctly, never double-books, never recovers into the
past, and accounts for the error budget.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orchestrator import (
    GroundStation,
    MockProviderAdapter,
    Reconciler,
    schedule_greedy,
)
from orchestrator.domain import ContactWindow
from orchestrator.scheduler import ScheduledContact, SchedulePlan

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

STATIONS = [
    GroundStation("GW-A", 0.0, 0.0, provider="prov-a"),
    GroundStation("GW-B", 10.0, 10.0, provider="prov-b"),
]


def win(sat, station, start_min, dur_min=8, peak=45.0):
    aos = T0 + timedelta(minutes=start_min)
    los = aos + timedelta(minutes=dur_min)
    return ContactWindow(sat, station, aos, aos + timedelta(minutes=dur_min / 2), los,
                         peak, 0.0, 180.0, dur_min * 60.0)


def plan_of(*windows, provider_by_station):
    scheduled = [ScheduledContact(w, provider_by_station[w.station], 1.0) for w in windows]
    return SchedulePlan(scheduled=scheduled, dropped=[])


PROVIDERS = {"GW-A": "prov-a", "GW-B": "prov-b"}


def test_clean_run_all_succeed():
    opps = [win("SAT", "GW-A", 0), win("SAT", "GW-A", 30)]
    plan = schedule_greedy(opps, STATIONS)
    adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=0.0),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=0.0)}
    report = Reconciler(adapters, STATIONS, opps).run(plan)

    assert report.satisfied == report.planned
    assert report.recoveries_booked == 0
    assert report.slo_met
    assert report.achieved_yield == 1.0


def test_failure_is_recovered_on_another_provider():
    # The only scheduled contact is on prov-a, which always fails. A later
    # opportunity exists on prov-b, which always succeeds.
    failing = win("SAT", "GW-A", 0)
    backup = win("SAT", "GW-B", 60)
    opps = [failing, backup]
    plan = plan_of(failing, provider_by_station=PROVIDERS)

    adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=1.0),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=0.0)}
    report = Reconciler(adapters, STATIONS, opps).run(plan)

    assert report.recoveries_booked >= 1
    assert report.satisfied == 1                       # demand ultimately met
    assert report.recovered_demands == 1               # via a recovery, not the original
    # the successful attempt was on the other provider
    succeeded = [a for a in report.attempts if a.state.value == "succeeded"]
    assert any(a.provider == "prov-b" for a in succeeded)


def test_recovery_is_never_in_the_past():
    failing = win("SAT", "GW-A", 100)
    earlier = win("SAT", "GW-B", 10)   # before the failure -> must NOT be used
    later = win("SAT", "GW-B", 200)
    opps = [earlier, failing, later]
    plan = plan_of(failing, provider_by_station=PROVIDERS)
    adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=1.0),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=0.0)}
    report = Reconciler(adapters, STATIONS, opps).run(plan)

    for a in report.attempts:
        if a.recovers is not None:
            assert a.window.aos > a.recovers.los   # recovery strictly after failure


def test_recovery_never_double_books():
    # prov-a fails; the recovery candidate on GW-B overlaps a contact already
    # booked on GW-B, so it must not be chosen.
    failing = win("SAT-1", "GW-A", 0)
    occupied = win("SAT-2", "GW-B", 60)        # already in the plan
    clash = win("SAT-1", "GW-B", 61)           # would overlap `occupied`
    opps = [failing, occupied, clash]
    plan = plan_of(failing, occupied, provider_by_station=PROVIDERS)
    adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=1.0),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=0.0)}
    report = Reconciler(adapters, STATIONS, opps).run(plan)

    booked_on_b = [a.window for a in report.attempts if a.window.station == "GW-B"]
    for i in range(len(booked_on_b)):
        for j in range(i + 1, len(booked_on_b)):
            a, b = booked_on_b[i], booked_on_b[j]
            assert not (a.aos < b.los and b.aos < a.los)


def test_max_recovery_attempts_bounds_thrash():
    # Everything fails and there are many alternatives; the loop must stop.
    failing = win("SAT", "GW-A", 0)
    alts = [win("SAT", "GW-B", 60 + 30 * i) for i in range(10)]
    opps = [failing] + alts
    plan = plan_of(failing, provider_by_station=PROVIDERS)
    adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=1.0),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=1.0)}
    report = Reconciler(adapters, STATIONS, opps, max_recovery_attempts=2).run(plan)

    # 1 original + at most 2 recoveries for the single demand
    assert len(report.attempts) <= 3
    assert report.satisfied == 0
    assert not report.slo_met


def test_error_budget_accounting():
    # 4 demands, one unrecoverable; SLO 0.95 tolerates floor(0.05*4)=0 -> not met.
    opps = [win(f"S{i}", "GW-A", i * 30) for i in range(4)]
    plan = schedule_greedy(opps, STATIONS)
    adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=0.0),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=0.0)}
    # Knock out exactly one demand with a targeted outage.
    failed = plan.scheduled[1].window
    adapters["prov-a"] = MockProviderAdapter(
        "prov-a", outages=[("GW-A", failed.aos, failed.los)])
    report = Reconciler(adapters, STATIONS, opps, slo_target=0.95).run(plan)

    assert report.unrecovered == 1
    assert report.error_budget == 0
    assert not report.slo_met


def test_determinism():
    opps = [win("SAT", "GW-A", i * 20) for i in range(6)]
    plan = schedule_greedy(opps, STATIONS)

    def run_once():
        adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=0.5, seed=7),
                    "prov-b": MockProviderAdapter("prov-b", failure_rate=0.5, seed=7)}
        return Reconciler(adapters, STATIONS, opps).run(plan)

    r1, r2 = run_once(), run_once()
    assert (r1.satisfied, r1.recoveries_booked) == (r2.satisfied, r2.recoveries_booked)
