"""End-to-end integration tests for the full orchestrator spine.

These tests exercise: TLE loading -> visibility -> scheduling ->
reconciliation -> observability, validating the complete data flow.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestrator import (
    GroundStation,
    MockProviderAdapter,
    Reconciler,
    compute_metrics,
    load_satellites_from_file,
    prometheus_metrics,
    render_html,
    save_report,
    load_report,
    schedule_greedy,
)
from orchestrator.visibility import compute_all_opportunities


@pytest.fixture
def tle_file(tmp_path: Path) -> Path:
    """Sample TLE file with ISS-like orbit."""
    tle_content = """ISS (ZARYA)
1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025
2 25544  51.6400 208.9163 0006703 296.7361 144.3228 15.49952836  1001
"""
    p = tmp_path / "test.tle"
    p.write_text(tle_content)
    return p


@pytest.fixture
def stations() -> list[GroundStation]:
    """Ground station network spanning different latitudes."""
    return [
        GroundStation("FAIRBANKS", 64.8378, -147.7164, provider="owned"),
        GroundStation("PUNTA_ARENAS", -53.1638, -70.9171, provider="ksat"),
        GroundStation("SVALBARD", 78.2307, 15.6488, provider="ksat"),
    ]


class TestFullSpineIntegration:
    """Test the complete data flow from TLEs to dashboard."""

    def test_visibility_to_scheduler_to_reconciler(
        self, tle_file: Path, stations: list[GroundStation]
    ) -> None:
        # 1. Load TLEs
        satellites = load_satellites_from_file(str(tle_file))
        assert len(satellites) == 1

        # 2. Compute visibility (24h window)
        now = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        end = now + timedelta(hours=24)
        opportunities = compute_all_opportunities(satellites, stations, now, end)

        # ISS should have passes over these stations in 24h
        assert len(opportunities) >= 1, "Expected at least 1 opportunity in 24h"

        # 3. Schedule greedily
        plan = schedule_greedy(opportunities, stations)
        assert plan.scheduled_count >= 0
        assert plan.scheduled_count + plan.dropped_count == len(opportunities)

        if plan.scheduled_count == 0:
            pytest.skip("No contacts scheduled (geometry dependent)")

        # 4. Run reconciler with mock adapters (no failures)
        adapters = {
            "owned": MockProviderAdapter("owned", failure_rate=0.0, seed=42),
            "ksat": MockProviderAdapter("ksat", failure_rate=0.0, seed=42),
        }
        report = Reconciler(adapters, stations, opportunities).run(plan)

        # 5. Verify report
        assert report.satisfied == report.planned
        assert report.slo_met
        assert report.achieved_yield == 1.0

        # 6. Generate observability outputs
        metrics = compute_metrics(report)
        assert metrics.planned == plan.scheduled_count

        prom = prometheus_metrics(report)
        assert "orchestrator_downlink_yield" in prom

        html = render_html(report)
        assert "<!doctype html>" in html.lower()

    def test_reconciler_recovery_flow(
        self, tle_file: Path, stations: list[GroundStation]
    ) -> None:
        """Test that recovery paths work end-to-end."""
        satellites = load_satellites_from_file(str(tle_file))
        now = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        opportunities = compute_all_opportunities(
            satellites, stations, now, now + timedelta(hours=24)
        )

        if len(opportunities) < 2:
            pytest.skip("Need at least 2 opportunities to test recovery")

        plan = schedule_greedy(opportunities, stations)

        if plan.scheduled_count == 0:
            pytest.skip("No contacts scheduled")

        # Inject 50% failure rate to trigger recoveries
        adapters = {
            "owned": MockProviderAdapter("owned", failure_rate=0.5, seed=123),
            "ksat": MockProviderAdapter("ksat", failure_rate=0.5, seed=456),
        }
        report = Reconciler(
            adapters, stations, opportunities, slo_target=0.5
        ).run(plan)

        # With failures, some recovery attempts may occur
        assert len(report.attempts) >= report.planned

    def test_report_persistence_roundtrip(
        self, tle_file: Path, stations: list[GroundStation], tmp_path: Path
    ) -> None:
        """Test save_report/load_report preserves data."""
        satellites = load_satellites_from_file(str(tle_file))
        now = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        opportunities = compute_all_opportunities(
            satellites, stations, now, now + timedelta(hours=12)
        )

        if len(opportunities) == 0:
            pytest.skip("No opportunities in window")

        plan = schedule_greedy(opportunities, stations)

        if plan.scheduled_count == 0:
            pytest.skip("No contacts scheduled")

        adapters = {
            "owned": MockProviderAdapter("owned"),
            "ksat": MockProviderAdapter("ksat"),
        }
        report = Reconciler(adapters, stations, opportunities).run(plan)

        # Save and reload
        path = tmp_path / "report.json"
        save_report(report, str(path))
        loaded = load_report(str(path))

        # Verify key fields preserved
        assert loaded.planned == report.planned
        assert loaded.satisfied == report.satisfied
        assert len(loaded.attempts) == len(report.attempts)
        assert loaded.slo_target == report.slo_target


class TestBundledTLEIntegration:
    """Test with the bundled ISS TLE file."""

    def test_bundled_tle_loads_and_computes(self) -> None:
        """Verify the bundled sample TLE works end-to-end."""
        tle_path = Path(__file__).parent.parent / "data" / "sample_tle.txt"
        if not tle_path.exists():
            pytest.skip("Bundled TLE file not found")

        satellites = load_satellites_from_file(str(tle_path))
        assert len(satellites) >= 1

        stations = [
            GroundStation("TEST_STATION", 40.0, -100.0, provider="test"),
        ]

        now = datetime.now(timezone.utc)
        opportunities = compute_all_opportunities(
            satellites, stations, now, now + timedelta(hours=6)
        )

        # Just verify it runs without error - actual passes depend on TLE epoch
        assert isinstance(opportunities, list)
