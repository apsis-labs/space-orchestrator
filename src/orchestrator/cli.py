"""Command-line interface for space-orchestrator.

Usage:
    orchestrator passes --hours 12
    orchestrator schedule --hours 24 --output plan.json
    orchestrator reconcile --plan plan.json --failure-rate 0.2
    orchestrator dashboard --report report.json --output status.html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from .domain import GroundStation
from .observability import render_html, save_report, load_report
from .providers import MockProviderAdapter
from .reconciler import Reconciler
from .scheduler import schedule_greedy
from .tle import load_satellites_from_file
from .visibility import compute_all_opportunities


def _load_stations(path: Path) -> list[GroundStation]:
    """Load stations from JSON file."""
    with open(path) as f:
        data = json.load(f)
    return [
        GroundStation(
            name=s["name"],
            latitude_deg=s["latitude_deg"],
            longitude_deg=s["longitude_deg"],
            elevation_m=s.get("elevation_m", 0.0),
            min_elevation_deg=s.get("min_elevation_deg", 5.0),
            provider=s.get("provider", "unknown"),
        )
        for s in data
    ]


def _default_stations_path() -> Path:
    """Return path to bundled stations.json."""
    return Path(__file__).parent.parent.parent / "data" / "stations.json"


def _default_tle_path() -> Path:
    """Return path to bundled sample_tle.txt."""
    return Path(__file__).parent.parent.parent / "data" / "sample_tle.txt"


def cmd_passes(args: argparse.Namespace) -> int:
    """List upcoming visibility windows."""
    tle_path = Path(args.tle) if args.tle else _default_tle_path()
    stations_path = Path(args.stations) if args.stations else _default_stations_path()

    if not tle_path.exists():
        print(f"Error: TLE file not found: {tle_path}", file=sys.stderr)
        return 1
    if not stations_path.exists():
        print(f"Error: Stations file not found: {stations_path}", file=sys.stderr)
        return 1

    satellites = load_satellites_from_file(str(tle_path))
    stations = _load_stations(stations_path)

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=args.hours)

    print(f"Computing passes from {now.isoformat()} to {end.isoformat()}")
    print(f"Satellites: {len(satellites)}, Stations: {len(stations)}")
    print()

    opportunities = compute_all_opportunities(satellites, stations, now, end)

    if not opportunities:
        print("No passes found in window.")
        return 0

    # Sort by AOS
    opportunities.sort(key=lambda w: w.aos)

    print(f"{'Satellite':<20} {'Station':<15} {'AOS (UTC)':<20} {'LOS (UTC)':<20} {'Peak':<6} {'Duration':<10}")
    print("-" * 95)

    for w in opportunities:
        aos_str = w.aos.strftime("%Y-%m-%d %H:%M:%S")
        los_str = w.los.strftime("%H:%M:%S")
        duration = int((w.los - w.aos).total_seconds() / 60)
        print(f"{w.satellite:<20} {w.station:<15} {aos_str:<20} {los_str:<20} {w.peak_elevation_deg:>5.1f}° {duration:>6} min")

    print()
    print(f"Total: {len(opportunities)} passes")

    if args.output:
        output_path = Path(args.output)
        data = [
            {
                "satellite": w.satellite,
                "station": w.station,
                "aos": w.aos.isoformat(),
                "tca": w.tca.isoformat(),
                "los": w.los.isoformat(),
                "peak_elevation_deg": w.peak_elevation_deg,
                "aos_azimuth_deg": w.aos_azimuth_deg,
                "los_azimuth_deg": w.los_azimuth_deg,
                "duration_s": w.duration_s,
            }
            for w in opportunities
        ]
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved to {output_path}")

    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    """Compute a contact schedule."""
    tle_path = Path(args.tle) if args.tle else _default_tle_path()
    stations_path = Path(args.stations) if args.stations else _default_stations_path()

    if not tle_path.exists():
        print(f"Error: TLE file not found: {tle_path}", file=sys.stderr)
        return 1

    satellites = load_satellites_from_file(str(tle_path))
    stations = _load_stations(stations_path)

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=args.hours)

    print(f"Computing schedule for {args.hours}h window...")

    opportunities = compute_all_opportunities(satellites, stations, now, end)
    plan = schedule_greedy(opportunities, stations)

    print(f"Scheduled: {plan.scheduled_count} contacts")
    print(f"Dropped (conflicts): {plan.dropped_count}")

    if args.output:
        output_path = Path(args.output)
        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_start": now.isoformat(),
            "window_end": end.isoformat(),
            "scheduled": [
                {
                    "satellite": c.window.satellite,
                    "station": c.window.station,
                    "provider": c.provider,
                    "aos": c.window.aos.isoformat(),
                    "los": c.window.los.isoformat(),
                    "peak_elevation_deg": c.window.peak_elevation_deg,
                }
                for c in plan.scheduled
            ],
            "dropped": [
                {
                    "satellite": c.window.satellite,
                    "station": c.window.station,
                    "aos": c.window.aos.isoformat(),
                }
                for c in plan.dropped
            ],
        }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved plan to {output_path}")

    return 0


def cmd_reconcile(args: argparse.Namespace) -> int:
    """Run reconciliation with mock adapters."""
    tle_path = Path(args.tle) if args.tle else _default_tle_path()
    stations_path = Path(args.stations) if args.stations else _default_stations_path()

    satellites = load_satellites_from_file(str(tle_path))
    stations = _load_stations(stations_path)

    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=args.hours)

    opportunities = compute_all_opportunities(satellites, stations, now, end)
    plan = schedule_greedy(opportunities, stations)

    if plan.scheduled_count == 0:
        print("No contacts scheduled. Nothing to reconcile.")
        return 0

    # Create mock adapters for each provider
    providers = {s.provider for s in stations}
    adapters = {
        p: MockProviderAdapter(p, failure_rate=args.failure_rate, seed=args.seed)
        for p in providers
    }

    print(f"Running reconciliation with {args.failure_rate:.0%} failure rate...")
    print(f"Providers: {', '.join(providers)}")
    print(f"Scheduled contacts: {plan.scheduled_count}")

    reconciler = Reconciler(
        adapters=adapters,
        stations=stations,
        opportunities=opportunities,
        slo_target=args.slo,
    )
    report = reconciler.run(plan)

    print()
    print(f"Results:")
    print(f"  Planned:     {report.planned}")
    print(f"  Satisfied:   {report.satisfied}")
    print(f"  Recoveries:  {report.recoveries_booked}")
    print(f"  Yield:       {report.achieved_yield:.1%}")
    print(f"  SLO target:  {report.slo_target:.1%}")
    print(f"  SLO met:     {'Yes' if report.slo_met else 'No'}")

    if args.output:
        output_path = Path(args.output)
        save_report(report, str(output_path))
        print(f"\nSaved report to {output_path}")

    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Generate HTML dashboard from a reconciliation report."""
    report_path = Path(args.report)

    if not report_path.exists():
        print(f"Error: Report file not found: {report_path}", file=sys.stderr)
        return 1

    report = load_report(str(report_path))

    html = render_html(report, title=args.title)

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        f.write(html)

    print(f"Dashboard saved to {output_path}")
    print(f"Open in browser: file://{output_path.absolute()}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Vendor-neutral satellite ground station contact scheduler.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # passes command
    passes_parser = subparsers.add_parser("passes", help="List upcoming visibility windows")
    passes_parser.add_argument("--tle", help="Path to TLE file (default: bundled ISS)")
    passes_parser.add_argument("--stations", help="Path to stations JSON (default: bundled)")
    passes_parser.add_argument("--hours", type=float, default=12, help="Window duration in hours (default: 12)")
    passes_parser.add_argument("--output", "-o", help="Save passes to JSON file")
    passes_parser.set_defaults(func=cmd_passes)

    # schedule command
    schedule_parser = subparsers.add_parser("schedule", help="Compute a contact schedule")
    schedule_parser.add_argument("--tle", help="Path to TLE file")
    schedule_parser.add_argument("--stations", help="Path to stations JSON")
    schedule_parser.add_argument("--hours", type=float, default=24, help="Window duration (default: 24)")
    schedule_parser.add_argument("--output", "-o", help="Save schedule to JSON file")
    schedule_parser.set_defaults(func=cmd_schedule)

    # reconcile command
    reconcile_parser = subparsers.add_parser("reconcile", help="Run reconciliation with mock adapters")
    reconcile_parser.add_argument("--tle", help="Path to TLE file")
    reconcile_parser.add_argument("--stations", help="Path to stations JSON")
    reconcile_parser.add_argument("--hours", type=float, default=24, help="Window duration (default: 24)")
    reconcile_parser.add_argument("--failure-rate", type=float, default=0.0, help="Mock failure rate 0-1 (default: 0)")
    reconcile_parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    reconcile_parser.add_argument("--slo", type=float, default=0.95, help="SLO target 0-1 (default: 0.95)")
    reconcile_parser.add_argument("--output", "-o", help="Save report to JSON file")
    reconcile_parser.set_defaults(func=cmd_reconcile)

    # dashboard command
    dashboard_parser = subparsers.add_parser("dashboard", help="Generate HTML dashboard from report")
    dashboard_parser.add_argument("--report", "-r", required=True, help="Path to reconciliation report JSON")
    dashboard_parser.add_argument("--output", "-o", default="dashboard.html", help="Output HTML file")
    dashboard_parser.add_argument("--title", default="Ground Segment Status", help="Dashboard title")
    dashboard_parser.set_defaults(func=cmd_dashboard)

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
