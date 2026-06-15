"""Tests for the observability layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orchestrator import (
    GroundStation,
    MockProviderAdapter,
    Reconciler,
    compute_metrics,
    format_report_for_narration,
    format_trend_for_narration,
    prometheus_metrics,
    render_html,
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


def _recovered_report():
    failing = win("SAT", "GW-A", 0)
    backup = win("SAT", "GW-B", 60)
    opps = [failing, backup]
    plan = SchedulePlan([ScheduledContact(failing, "prov-a", 1.0)], [])
    adapters = {"prov-a": MockProviderAdapter("prov-a", failure_rate=1.0),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=0.0)}
    return Reconciler(adapters, STATIONS, opps).run(plan)


def test_metrics_match_report():
    report = _recovered_report()
    m = compute_metrics(report)
    assert m.planned == 1
    assert m.satisfied == 1
    assert m.recovered == 1
    assert m.unrecovered == 0
    assert m.achieved_yield == 1.0


def test_per_provider_success_rates():
    report = _recovered_report()
    m = compute_metrics(report)
    rates = {p.provider: p.success_rate for p in m.providers}
    assert rates["prov-a"] == 0.0   # the original failed
    assert rates["prov-b"] == 1.0   # the recovery succeeded


def test_prometheus_contains_core_series():
    report = _recovered_report()
    text = prometheus_metrics(report)
    assert "orchestrator_downlink_yield 1.000000" in text
    assert "orchestrator_slo_met 1" in text
    assert 'orchestrator_provider_success_rate{provider="prov-b"} 1.000000' in text


def test_html_is_self_contained_and_has_numbers():
    report = _recovered_report()
    html = render_html(report, title="Test Run")
    assert html.startswith("<!doctype html>")
    assert "<svg" in html              # the timeline / orb rendered
    assert "100" in html               # yield number present
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")  # no external deps


def test_breached_slo_is_reported():
    # One unrecoverable demand, SLO 0.95 -> budget 0 -> breached.
    opps = [win(f"S{i}", "GW-A", i * 30) for i in range(3)]
    plan = schedule_greedy(opps, STATIONS)
    failed = plan.scheduled[0].window
    adapters = {"prov-a": MockProviderAdapter("prov-a", outages=[("GW-A", failed.aos, failed.los)]),
                "prov-b": MockProviderAdapter("prov-b", failure_rate=0.0)}
    report = Reconciler(adapters, STATIONS, opps, slo_target=0.95).run(plan)
    m = compute_metrics(report)
    assert not m.slo_met
    assert "DEGRADED" in render_html(report)  # new verdict language


def test_format_report_for_narration():
    report = _recovered_report()
    text = format_report_for_narration(report)
    assert "RECONCILIATION SUMMARY" in text
    assert "Achieved yield" in text
    assert "Per-provider reliability" in text
    assert "RECOVERY" in text or "PLANNED" in text  # event tagging


def test_format_trend_for_narration():
    r1 = _recovered_report()
    r2 = _recovered_report()  # same for simplicity
    text = format_trend_for_narration([r1, r2])
    assert "TREND SUMMARY" in text
    assert "Average yield" in text
    assert "Constellation" not in text  # this is the narration version, not the HTML
